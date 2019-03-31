import logging
import time
import urllib.parse
import pymongo
import re

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver import ActionChains
from selenium.common.exceptions import TimeoutException

from error import TaoBaoLoginError


PREFS = {
        'profile.default_content_setting_values.images': 2
    }

# 淘宝账号
USER = ''
# 淘宝密码
PASSWD = ''

# mongodb配置
MONGO_URI = 'mongodb://localhost:27017/'
MONGO_DB = 'taobao'
COLLECTION = 'books'


class TaoBaoBase(object):
    """基本配置和方法类"""

    logger = logging.getLogger(__name__)

    def __init__(self, perfs=PREFS, mongo_uri=MONGO_URI, mongo_db=MONGO_DB, collection=COLLECTION):
        """
        :param perfs: 禁止加载图片
        :param mongo_uri mongodb数据库连接地址
        :param mongo_db 数据库名称
        :param collection 文档名称
        """
        self.options = webdriver.ChromeOptions()
        self.options.add_experimental_option('excludeSwitches', ['enable-automation'])
        self.options.add_experimental_option('prefs', perfs)

        self.options.add_argument('lang=zh_CN.UTF-8')
        self.options.add_argument('''Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/72.0.3626.121 Safari/537.36''')

        self.browser = webdriver.Chrome(chrome_options=self.options)
        # 存储窗口具柄
        self.window_handles = []

        # 配置MongoDb
        client = pymongo.MongoClient(mongo_uri)
        self.db = client[mongo_db]
        self.collection = self.db[collection]

    def __del__(self):
        print("关闭chromeDriver")
        self.browser.quit()

    def make_request(self, urls, callback=None, now_window=False):
        """
        构造请求
        :param now_window: 在浏览器里面开启新的选项卡
        :param window: 在新窗口中打开url
        :param urls: 传入urls列表
        :param callback: 回调函数
        :return: None
        """
        if isinstance(urls, str):
            urls = [urls]
        if now_window:
            self._send_request(urls, callback=callback)
        else:
            for url in urls:
                self.browser.get(url)
                if callback is not None:
                    callback()

    def _send_request(self, urls, callback=None):
        # 打开新窗口
        self.window_handles.clear()
        for url in urls:
            print(url)
            js = 'window.open("{}");'.format(url)
            self.browser.execute_script(js)
        self.window_handles = self.browser.window_handles
        if callback is not None:
            callback()

    def delete_blank(self, s):
        """
        删除空格
        :param s: 字符串
        :return: 字符串或者其他类型对象
        """
        if isinstance(s, str):
            return ''.join(s.split())
        return s


class TaobaoLogin(TaoBaoBase):
    """淘宝模拟登陆"""
    def __init__(self):
        self._failure_num = 0
        self._failure_count = 5
        # 淘宝登陆地址
        self.login_url = 'https://login.taobao.com/member/login.jhtml'
        super(TaobaoLogin, self).__init__()

    def _get_page(self):
        """访问登陆页"""
        self.make_request(self.login_url)

    def _execute_login(self, user=USER, passwd=PASSWD):
        """
        输入账号密码
        :param user: 账号
        :param passwd: 密码
        """
        is_input_passwd = self.browser.find_elements(By.CSS_SELECTOR, '.module-quick')
        if is_input_passwd:
            # 判断是否是输入账号密码页面
            self.browser.find_element_by_css_selector('#J_Quick2Static').click()
        name_node = self.browser.find_element(By.CSS_SELECTOR, '#TPL_username_1')
        # 查看用户名输入框是否已经有用户名，已经存在用户名的话需要先清空
        name_node.clear()
        # 输入用户名和密码
        name_node.send_keys(user)
        self.browser.find_element_by_css_selector('#TPL_password_1').send_keys(passwd)
        # 判断是否需要输入验证码
        try:
            WebDriverWait(self.browser, 10).until(
                EC.presence_of_element_located((By.XPATH, '//div[@id="nocaptcha" and @style="display: block;"]'))
            )
            sliding = self.browser.find_element(By.CSS_SELECTOR, '#nc_1_n1z')
            ActionChains(self.browser).click_and_hold(sliding).perform()
            self.logger.info("......正在滑动验证码")
            ActionChains(self.browser).move_by_offset(xoffset=300, yoffset=0).release().perform()
        except TimeoutException:
            print("......没有滑动验证码")
        else:
            self.browser.find_element(By.CSS_SELECTOR, '#J_SubmitStatic').click()

    def _check_login(self):
        """
        校验登陆是否成功
        :return:
        """
        time.sleep(3)
        if urllib.parse.urlparse(self.browser.current_url)[1] in ['i.taobao.com']:
            print("登陆成功")
            return True
        else:
            # 记录淘宝登陆失败次数，如果失败过多抛出异常
            if self._failure_num <= self._failure_count:
                print('登陆失败%s次' % self._failure_num)
                self._failure_num += 1
                self.login()
            else:
                raise TaoBaoLoginError

    def login(self):
        """
        淘宝登陆主函数
        :return:
        """
        self._get_page()
        self._execute_login()
        self._check_login()


class Taobao(TaobaoLogin):
    """根据商品搜索爬取淘宝详情页商品数据"""
    def __init__(self):
        # 搜索的具体商品和页码
        self.search_url = 'https://s.taobao.com/search?q={0}&s={1}'
        self.tb = ''
        self.tm = 'detail.tmall.com'
        super(Taobao, self).__init__()

    def parse_pages(self):
        """
        商品列表页
        :return:
        """
        # 解析商品详情页url地址
        detail_links = [detail.get_attribute('href') for detail in
                        self.browser.find_elements_by_css_selector('.pic-link.J_ClickStat.J_ItemPicA')]
        detail_links = list(filter(lambda x: self.tm in x, detail_links))
        self.make_request(detail_links, callback=self.parse_detail)

    def parse_page_links(self, name):
        """
        解析商品列表页总url地址数量，再根据url规律构建出url地址
        """
        self.make_request(self.search_url.format(name, 0))
        total_page = WebDriverWait(self.browser, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '.total'))
        ).text
        re_result = re.match(r'.*?(\d+).*', total_page)
        if re_result:
            total_page = int(re_result.group(1))
        if isinstance(total_page, int):
            # 根据url规律构建出淘宝商品列表页的url地址
            self.search_url = [self.search_url.format(name, number * 44) for number in range(0, total_page)]

    def parse_detail(self):
        """
        解析商品详情页
        """
        wait = WebDriverWait(self.browser, 30)
        try:
            title = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'h1[data-spm="1000983"]'))
            ).text
            month_sales = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, '.tm-ind-sellCount .tm-count'))
            ).text
            review_count = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, '.tm-ind-reviewCount .tm-count'))
            ).text
            stock = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, '#J_EmStock'))
            ).text
            url = self.browser.current_url
            product_attr = [element.text for element in self.browser.find_elements_by_css_selector('#J_AttrUL>li')]
        except TimeoutException:
            print("解析商品详情页超时......")
        else:
            item = {'url': url, 'title': title, 'month_sales': month_sales, 'review_count': review_count, 'stock': stock, 'product_attr': product_attr}
            for key, value in list(item.items()):
                item[key] = self.delete_blank(value)
            self.inser_db(item)

    def inser_db(self, item):
        """
        保存到mongo_db数据库
        :param item: 数据
        """
        print(item)
        self.collection.insert_one(item)

    def search(self, name):
        """
        爬取淘宝商品信息主入口
        :param name: 在淘宝搜索框搜索的内容(需要爬取内容的关键字)
        """
        self.login()
        self.parse_page_links(name)
        self.make_request(self.search_url, self.parse_pages)


if __name__ == '__main__':
    taobao = Taobao()
    taobao.search('python')