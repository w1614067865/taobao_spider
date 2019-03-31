class TaoBaoLoginError(Exception):
    """登陆失败次数过多，就会抛出此异常"""
    def __init__(self):
        super(TaoBaoLoginError, self).__init__()

    def __str__(self):
        return repr("登陆密码错误或模拟登陆失效")