from config.logger import setup_logging
import json
from core.handle.abortHandle import handleAbortMessage
from core.handle.helloHandle import handleHelloMessage
from core.utils.util import remove_punctuation_and_length
from core.handle.receiveAudioHandle import startToChat, handleAudioMessage
from core.handle.sendAudioHandle import send_stt_message, send_tts_message
from core.handle.iotHandle import handleIotDescriptors, handleIotStatus
import asyncio

TAG = __name__
logger = setup_logging()


async def handleTextMessage(conn, message):
    """处理文本消息"""
    logger.bind(tag=TAG).info(f"收到文本消息：{message}")
    try:
        msg_json = json.loads(message)
        if isinstance(msg_json, int):
            await conn.websocket.send(message)
            return
        if msg_json["type"] == "hello":
            await handleHelloMessage(conn)
        elif msg_json["type"] == "abort":
            await handleAbortMessage(conn)
        elif msg_json["type"] == "listen":
            if "mode" in msg_json:
                conn.client_listen_mode = msg_json["mode"]
                logger.bind(tag=TAG).debug(f"客户端拾音模式：{conn.client_listen_mode}")
            if "sensor" in msg_json:
                conn.client_have_voice = True
                conn.client_voice_stop = False
                await handleSensorMessage(conn, msg_json)
                return
            if msg_json["state"] == "start":
                conn.client_have_voice = True
                conn.client_voice_stop = False
            elif msg_json["state"] == "stop":
                conn.client_have_voice = True
                conn.client_voice_stop = True
                if len(conn.asr_audio) > 0:
                    await handleAudioMessage(conn, b"")
            elif msg_json["state"] == "detect":
                conn.asr_server_receive = False
                conn.client_have_voice = False
                conn.asr_audio.clear()
                if "text" in msg_json:
                    text = msg_json["text"]
                    _, text = remove_punctuation_and_length(text)

                    # 识别是否是唤醒词
                    is_wakeup_words = text in conn.config.get("wakeup_words")
                    # 是否开启唤醒词回复
                    enable_greeting = conn.config.get("enable_greeting", True)

                    if is_wakeup_words and not enable_greeting:
                        # 如果是唤醒词，且关闭了唤醒词回复，就不用回答
                        await send_stt_message(conn, text)
                        await send_tts_message(conn, "stop", None)
                    elif is_wakeup_words:
                        await startToChat(conn, "嘿，你好呀")
                    else:
                        # 否则需要LLM对文字内容进行答复
                        await startToChat(conn, text)
        elif msg_json["type"] == "iot":
            if "descriptors" in msg_json:
                asyncio.create_task(handleIotDescriptors(conn, msg_json["descriptors"]))
            if "states" in msg_json:
                asyncio.create_task(handleIotStatus(conn, msg_json["states"]))
        elif msg_json["type"] == "server":
            # 如果配置是从API读取的，则需要验证secret
            read_config_from_api = conn.config.get("read_config_from_api", False)
            if not read_config_from_api:
                return
            # 获取post请求的secret
            post_secret = msg_json.get("content", {}).get("secret", "")
            secret = conn.config["manager-api"].get("secret", "")
            # 如果secret不匹配，则返回
            if post_secret != secret:
                await conn.websocket.send(json.dumps({
                    "type": "config_update_response",
                    "status": "error",
                    "message": "服务器密钥验证失败"
                }))
                return
            # 动态更新配置
            if msg_json["action"] == "update_config":
                await conn.handle_config_update(msg_json)
    except json.JSONDecodeError:
        await conn.websocket.send(message)

async def handleSensorMessage(conn, message):
    first = bool(message["wakeup"])
    sensor = message["sensor"]
    value = int(message["sensor_value"])
    msg = ''
    if 'hug' in sensor:
        msg = "[hug]"  # 用户拥抱
    elif 'head' in sensor:
        msg = "[head]"  # 用户摸头
    elif 'left_hand' in sensor:
        msg = "[sl]"  # 用户握手（左手）
    elif 'right_hand' in sensor:
        msg = "[sr]"  # 用户握手（右手）
    logger.bind(tag=TAG).info(f"传感器事件: {sensor}, 消息: {msg}, 值: {value}, 是否首次: {first}")
    # if first:
    #     msg += ""
    await startToChat(conn, msg)