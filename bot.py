from state import StateManager
from pyrogram import Client, filters, types
from dotenv import load_dotenv
import os
load_dotenv()

api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")
bot_token = os.getenv("BOT_TOKEN")

app = Client(
    "anon",
    api_id=api_id,
    api_hash=api_hash,
    bot_token=bot_token,
    proxy={
        "scheme": "socks5",
        "hostname": "127.0.0.1",
        "port": 2080,
    }
)

manager = StateManager()


@app.on_message(filters.private & ~filters.regex(r'^/\w+'))
async def message_handler(client, message: types.Message):
    chat_id = message.chat.id
    if await manager.is_chatting(chat_id):
        reciever_id = await manager.get_reciever_id(chat_id)
        if await manager.is_chatting(reciever_id) and await manager.get_reciever_id(reciever_id) == chat_id:
            await app.copy_message(
                chat_id=reciever_id,
                from_chat_id=chat_id,
                message_id=message.id,
            )
        else:
            await manager.chat(chat_id, reciever_id, message.id)
    else:
        await app.send_message(chat_id, "در حال مکالمه نیستی", reply_to_message_id=message.id)


@app.on_message(filters.private & filters.command('start'))
async def start_handler(client, message: types.Message):
    chat_id = message.chat.id
    if message.text == '/start':
        await app.send_message(
            chat_id,
            f"""اینجا می‌تونی با افراد به صورت واقعا ناشناس مکالمه کنی!
            کافیه رو لینک زیر کلیک کنن تا بتونن باهات به صورت ناشناس حرف بزنن.
            https://t.me/TruAnonBot?start=chat-{chat_id}""",
            reply_to_message_id=message.id)
        return
    if message.text[7:12] == 'chat-':
        reciever_id = message.text[12:]
        if not reciever_id.isdigit():
            return
        reciever_id = int(reciever_id)
        if reciever_id == chat_id:
            await app.send_message(
                chat_id,
                f"با خودت نمی‌تونی چت کنی!",
                reply_to_message_id=message.id)
            return
        await manager.start_chat(chat_id, reciever_id)
        await app.send_message(
            chat_id,
            f"مکالمه شروع شد.",
            reply_to_message_id=message.id,
        )


@app.on_message(filters.private & filters.command('endchat'))
async def end_handler(client, message: types.Message):
    chat_id = message.chat.id
    if not await manager.is_chatting(chat_id):
        await app.send_message(
            chat_id,
            "شما در حال حاضر در مکالمه‌ای نیستید.",
            reply_to_message_id=message.id,
        )
        return
    await manager.end_chat(chat_id)
    await app.send_message(
        chat_id,
        "مکالمه پایان یافت.",
        reply_to_message_id=message.id,
    )


@app.on_message(filters.private & filters.command('block'))
async def block_handler(client, message: types.Message):
    chat_id = message.chat.id
    if not await manager.is_chatting(chat_id):
        await app.send_message(
            chat_id,
            "شما در حال حاضر در مکالمه‌ای نیستید.",
            reply_to_message_id=message.id,
        )
        return
    await app.send_message(
        chat_id,
        "آیا از بلاک کردن مخاطب مطمئن هستی؟",
        reply_to_message_id=message.id,
        reply_markup=types.InlineKeyboardMarkup(
            [
                [
                    types.InlineKeyboardButton(
                        "بلاک",
                        callback_data=f'block-{await manager.get_reciever_id(chat_id)}'
                    )
                ],
            ]
        )
    )


@app.on_callback_query(filters.regex(r'^block-\d+$'))
async def block_callback_handler(client, query: types.CallbackQuery):
    chat_id = query.message.chat.id
    sender_id = int(query.data[6:])
    await manager.block(chat_id, sender_id)
    await app.edit_message_reply_markup(
        chat_id,
        query.message.id,
        reply_markup=types.InlineKeyboardMarkup(
            [
                [
                    types.InlineKeyboardButton(
                        "آن‌بلاک",
                        callback_data=f'unblock-{sender_id}'
                    )
                ],
            ]
        )
    )
    await query.answer("بلاک شد")


@app.on_callback_query(filters.regex(r'^unblock-\d+$'))
async def unblock_callback_handler(client, query: types.CallbackQuery):
    chat_id = query.message.chat.id
    sender_id = int(query.data[8:])
    await manager.block(chat_id, sender_id)
    await app.edit_message_reply_markup(
        chat_id,
        query.message.id,
        reply_markup=types.InlineKeyboardMarkup(
            [
                [
                    types.InlineKeyboardButton(
                        "بلاک",
                        callback_data=f'block-{sender_id}'
                    )
                ],
            ]
        )
    )
    await query.answer("آن‌بلاک شد")


@app.on_message(filters.private & filters.command('inbox'))
async def inbox_handler(client, message: types.Message):
    chat_id = message.chat.id
    if await manager.is_chatting(chat_id):
        await app.send_message(
            chat_id,
            "برای بررسی صندوق پیام‌ها باید مکالمه فعلی خاتمه بیاید.",
            reply_to_message_id=message.id,
        )
        return
    sender_len, message_len = await manager.get_inbox_len(chat_id)
    if sender_len == 0:
        await app.send_message(
            chat_id,
            "پیام جدیدی ندارید.",
            reply_to_message_id=message.id,
        )
        return
    await app.send_message(
        chat_id,
        f"شما {message_len} پیام جدید از {sender_len} نفر دارید.",
        reply_to_message_id=message.id,
        reply_markup=types.InlineKeyboardMarkup(
            [
                [
                    types.InlineKeyboardButton(
                        "شروع مکالمه و دریافت پیام‌های یک نفر",
                        callback_data='inbox'
                    )
                ],
            ]
        )
    )


@app.on_callback_query(filters.regex(r'^inbox'))
async def inbox_callback_handler(client, query: types.CallbackQuery):
    chat_id = query.message.chat.id
    sender_len, message_len = await manager.get_inbox_len(chat_id)
    if sender_len == 0:
        await app.send_message(
            chat_id,
            "پیامی در صندوق پیام‌های شما موجود نیست",
        )
        return
    await app.edit_message_reply_markup(
        chat_id,
        query.message.id,
        reply_markup=None,
    )
    sender_id, messages = await manager.get_inbox(chat_id)
    await manager.start_chat(chat_id, sender_id)
    await query.answer("مکالمه شروع شد.")
    for message_id in messages:
        await app.copy_message(
            chat_id=chat_id,
            from_chat_id=sender_id,
            message_id=message_id,
        )


app.run()
