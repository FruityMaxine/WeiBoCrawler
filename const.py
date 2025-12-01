# -*- coding: utf-8 -*-

"""
全局常量容器
注意：以下值现在仅作为默认缺省值。
实际运行中，weibo.py 会从 config.json 读取配置并覆盖这里的值。
请勿直接修改此文件，请修改 WebUI 或 config.json。
"""

# 运行模式: overwrite (覆盖) / append (追加)
MODE = "overwrite"

# Cookie 有效性检查配置
CHECK_COOKIE = {
    "CHECK": False,            # 是否检查
    "CHECKED": False,          # [程序内部变量] 检查状态标记，勿动
    "EXIT_AFTER_CHECK": False, # 检查完是否直接退出
    "HIDDEN_WEIBO": "",        # 验证用的仅自己可见微博内容
    "GUESS_PIN": False         # [程序内部变量] 猜测置顶，勿动
}

# 通知服务配置 (PushDeer)
NOTIFY = {
    "NOTIFY": False,           # 是否开启通知
    "PUSH_KEY": ""             # PushDeer Key
}