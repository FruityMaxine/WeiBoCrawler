import requests
import logging

# 获取 weibo 的 logger，这样日志也能显示在 WebUI 里
logger = logging.getLogger("weibo")

def push_deer(push_key, text):
    """
    发送 PushDeer 通知
    :param push_key: PushDeer 的 Key
    :param text: 通知的文本内容
    """
    # 如果没有 Key，直接返回，不报错
    if not push_key:
        return
        
    params = {
        'pushkey': push_key,
        'text': text,
    }
    try:
        # 这里为了避免证书验证，使用http而非https
        # 设置 timeout=5 防止网络卡死
        requests.get(url="http://api2.pushdeer.com/message/push", params=params, timeout=5)
        logger.info("PushDeer 通知已发送")
    except Exception as e:
        logger.warning(f"PushDeer 通知发送失败: {e}")