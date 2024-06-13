import asyncio
from contextlib import suppress
from typing import Sequence

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from pytonapi.utils import userfriendly_to_raw, amount_to_nano

from app.config import TOKEN_CHECK_THRESHOLDS
from app.db.models import MemberDB, TokenDB, UserDB


def get_tokens_required(user: UserDB) -> int:
    user_date = user.created_at

    if user_date < TOKEN_CHECK_THRESHOLDS[0][0]:
        return TOKEN_CHECK_THRESHOLDS[0][1]

    for threshold_date, tokens in TOKEN_CHECK_THRESHOLDS:
        if user_date < threshold_date:
            return tokens

    return TOKEN_CHECK_THRESHOLDS[-1][1]


async def user_is_holder(user: UserDB, tokens: Sequence[TokenDB]):
    member_checks = []

    for token in tokens:
        member_address = (
            userfriendly_to_raw(user.wallet_address)
            if user and user.wallet_address
            else None
        )
        user_min_amount = amount_to_nano(get_tokens_required(user))
        if token.holders and token.holders.get(member_address, 0) >= user_min_amount:
            member_checks.append(True)
        else:
            member_checks.append(False)

    return all(member_checks)


async def kick_member(bot: Bot, member: MemberDB) -> None:
    with suppress(TelegramBadRequest):
        await bot.ban_chat_member(member.chat_id, member.user_id)
        await asyncio.sleep(.2)
        await bot.unban_chat_member(member.chat_id, member.user_id)
        await asyncio.sleep(.2)
