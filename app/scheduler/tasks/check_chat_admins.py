from __future__ import annotations

import asyncio
import json
import os
from contextlib import suppress
from dataclasses import dataclass
from typing import Sequence, List

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from pytonapi.utils import userfriendly_to_raw
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import BASE_DIR
from app.db.models import ChatDB, TokenDB, MemberDB

IGNORE_WALLETS = [
    "UQBe_hx43tkDqa4Fay6uKw5iSTHPmWpAdNiqEBzXH52t98nc"  # noqa
]


@dataclass
class UserHolder:
    user_id: str | int
    chat_id: int | str
    token_amount: int
    wallet_address: str


class HolderStorage:
    def __init__(self, filepath: str = f"{BASE_DIR}/db/data"):
        self.filepath = filepath
        self.filename = "holders.json"
        os.makedirs(self.filepath, exist_ok=True)

    def load(self) -> dict:
        file_path = os.path.join(self.filepath, self.filename)
        if not os.path.exists(file_path):
            return {"holders": []}

        with open(os.path.join(self.filepath, self.filename), "r") as f:
            return json.load(f)

    def save(self, data: dict) -> None:
        with open(os.path.join(self.filepath, self.filename), "w") as f:
            json.dump(data, f)


async def check_chat_admins() -> None:
    loop = asyncio.get_event_loop()
    bot: Bot = loop.__getattribute__("bot")
    sessionmaker: async_sessionmaker = loop.__getattribute__("sessionmaker")

    holder_storage = HolderStorage()

    old_holders = holder_storage.load()
    await demote_old_holders(bot, sessionmaker, old_holders)

    chats = await ChatDB.all(sessionmaker)
    members = await get_members_in_chat(sessionmaker, chats[0].id)

    tokens = await TokenDB.all(sessionmaker)
    holders_to_check = get_user_holders(tokens[0].holders, members)
    top_holders = sorted(holders_to_check, key=lambda holder: holder.token_amount, reverse=True)

    new_holders = await promote_top_holders(bot, sessionmaker, top_holders)
    holder_storage.save({"holders": new_holders})


async def get_members_in_chat(sessionmaker: async_sessionmaker, chat_id: int) -> Sequence[MemberDB]:
    return await MemberDB.all_by_filter(
        sessionmaker,
        join_tables=[MemberDB.user],
        chat_id=chat_id,
    )


def get_user_holders(holders: dict, members: Sequence[MemberDB]) -> List[UserHolder]:
    user_holders = []

    for member in members:
        if member.user.wallet_address in IGNORE_WALLETS:
            continue

        member_address = (
            userfriendly_to_raw(member.user.wallet_address)
            if member.user and member.user.wallet_address
            else None
        )

        if member_address in holders:
            user_holders.append(
                UserHolder(
                    user_id=member.user_id,
                    chat_id=member.chat_id,
                    token_amount=holders[member_address],
                    wallet_address=member_address,
                )
            )

    return user_holders


async def demote_old_holders(bot: Bot, sessionmaker: async_sessionmaker, old_holders: dict) -> None:
    for holder in old_holders.get("holders", []):
        member = await MemberDB.get_by_filter(sessionmaker, user_id=holder["user_id"], chat_id=holder["chat_id"])
        if member:
            try:
                await remove_admin_role(bot, member)
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
                await remove_admin_role(bot, member)


async def promote_top_holders(bot: Bot, sessionmaker: async_sessionmaker, top_holders: List[UserHolder]) -> List[dict]:
    new_holders = []
    for holder in top_holders[:49 - len(IGNORE_WALLETS)]:
        member = await MemberDB.get_by_filter(sessionmaker, user_id=holder.user_id, chat_id=holder.chat_id)
        if member:
            title = f"{int(holder.token_amount)} $RANDOM"

            try:
                await set_admin_role(bot, member, title)
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
                await set_admin_role(bot, member, title)

            new_holders.append({"user_id": member.user_id, "chat_id": member.chat_id})

    return new_holders


async def set_admin_role(bot: Bot, member: MemberDB, title: str) -> None:
    with suppress(TelegramBadRequest):
        await bot.promote_chat_member(
            chat_id=member.chat_id,
            user_id=member.user_id,
            can_pin_messages=True,
        )
        await asyncio.sleep(1)

    try:
        await set_admin_title(bot, member, title)
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after + 1)
        await set_admin_title(bot, member, title)


async def set_admin_title(bot: Bot, member: MemberDB, title: str) -> None:
    await bot.set_chat_administrator_custom_title(
        chat_id=member.chat_id,
        user_id=member.user_id,
        custom_title=title,
    )
    await asyncio.sleep(1)


async def remove_admin_role(bot: Bot, member: MemberDB) -> None:
    with suppress(TelegramBadRequest):
        await bot.promote_chat_member(
            chat_id=member.chat_id,
            user_id=member.user_id,
            can_pin_messages=False,
        )
        await asyncio.sleep(1)
