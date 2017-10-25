from django.shortcuts import render, HttpResponse
from django.conf import settings

# Create your views here.
import requests
import time
import re
import json
import logging
import random

logger = logging.getLogger('wechat')
headers = {'User-Agent': settings.USER_AGENT}

def ticket(html):
    '''
    将微信返回的xml格式的通行证转为字典格式
    :param html: xml内容
    :return: 字典
    '''
    from bs4 import BeautifulSoup
    ret = {}
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup.find(name='error').find_all():
        ret[tag.name] = tag.text
    return ret


def login(req):
    if req.method == 'GET':
        url = '{}/jslogin'.format(settings.LOGIN_URL)
        params = {
            'appid': 'wx782c26e4c19acffb',
            'fun': 'new', }
        try:
            r = requests.get(url, params=params, headers=headers)
            regx = r'window.QRLogin.code = (\d+); window.QRLogin.uuid = "(\S+?)";'
            data = re.search(regx, r.text)

            if data and data.group(1) == '200':
                uuid = data.group(2)
                req.session['UUID'] = uuid
                return render(req, 'login.html', {'uuid': uuid})
        except:
            # logger.exception('this is an exception message')
            return HttpResponse('二维码加载失败，请稍后再试！')

def check_login(req):
    uuid = req.session['UUID']
    url = '{}/cgi-bin/mmwebwx-bin/login'.format(settings.LOGIN_URL)
    localTime = int(time.time() * 1000)
    params = {
        'loginicon': 'true',
        'uuid': uuid,
        'tip': 0,
        'r': -localTime,
        '_': localTime,
    }
    r1 = requests.get(url, params=params, headers=headers)
    # 设置返回默认值
    response = {'code': 408, 'data': None}

    if 'window.code=408' in r1.text:
        # 无人扫码
        response['code'] = 408
    elif 'window.code=201' in r1.text:
        # 扫码，返回头像data数据
        response['code'] = 201
        response['data'] = re.findall("window.userAvatar = '(.*)';", r1.text)[0]
    elif 'window.code=200' in r1.text:
        # 扫码，并确认登录
        req.session['LOGIN_COOKIE'] = r1.cookies.get_dict()  # 将每个环节的cookies保存下来，以备后用
        base_redirect_url = re.findall('redirect_uri="(.*)";', r1.text)[0]

        # 获取凭证
        r2 = requests.get(base_redirect_url, headers=headers, allow_redirects=False)
        # 将xml返回值转为字典
        ticket_dict = ticket(r2.text)
        # print(ticket_dict)
        req.session['TICKED_DICT'] = ticket_dict
        req.session['TICKED_COOKIE'] = r2.cookies.get_dict()

        # 初始化，获取最近联系人信息及公众号等  DeviceID  e384757757885382 随机生成
        post_data = {
            "BaseRequest": {
                "DeviceID": 'e' + repr(random.random())[2:17],
                'Sid': ticket_dict['wxsid'],
                'Uin': ticket_dict['wxuin'],
                'Skey': ticket_dict['skey'],
            }
        }
        req.session['POST_DATA'] = post_data   # 后面会用
        # 用户初始化，将最近联系人个人信息放在session中
        init_url = "{0}/webwxinit?r=-{1}&pass_ticket={2}" \
            .format(settings.MAIN_URL, localTime, ticket_dict['pass_ticket'])

        r3 = requests.post(
            url=init_url,
            headers=headers,
            json=post_data
        )
        r3.encoding = 'utf-8'
        init_dict = json.loads(r3.text)

        # 将所有初始化信息存入session
        req.session['INIT_DICT'] = init_dict
        response['code'] = 200
    return HttpResponse(json.dumps(response))


def avatar(req):
    '''
    用于生成头像的函数
    :param req:
    :return:
    '''
    prev = req.GET.get('prev')  # /cgi-bin/mmwebwx-bin/webwxgeticon?seq=602427528
    username = req.GET.get('username')  # @fb736164312cbcdb9abe746d81e24835
    skey = req.GET.get('skey')  # @crypt_2ccf8ab9_4414c9f723cbe6e9caca48b7deceff93
    img_url = "https://wx.qq.com{0}&username={1}&skey={2}".format(prev, username, skey)

    cookies = {}
    cookies.update(req.session['LOGIN_COOKIE'])
    cookies.update(req.session['TICKED_COOKIE'])
    # print(img_url)
    # 头像图片做了防盗链，需要加上header和cookies
    res = requests.get(img_url, cookies=cookies,
                       headers={'Content-Type': 'image/jpeg', 'User-Agent': settings.USER_AGENT})
    # print(res.content)  # 返回的是字节，可以直接返回给前端页面使用
    return HttpResponse(res.content)


def index(req):
    """显示最近联系人"""
    # https://wx.qq.com
    return render(req, 'index.html')


def contact_list(req):
    """
    获取所有联系人
    :param req:
    :return:
    """
    ctime = int(time.time() * 1000)
    base_url = "{0}/webwxgetcontact?lang=zh_CN&r={1}&seq=0&skey={2}"
    url = base_url.format(settings.MAIN_URL, ctime, req.session['TICKED_DICT']['skey'])
    cookies = {}
    cookies.update(req.session['LOGIN_COOKIE'])
    cookies.update(req.session['TICKED_COOKIE'])

    r1 = requests.get(url, cookies=cookies, headers=headers)
    r1.encoding = 'utf-8'

    user_list = json.loads(r1.text)

    return render(req, 'contact_list.html', {'user_list': user_list})


def send_msg(req):
    """
    发送消息
    :param req:
    :return:
    """
    current_user = req.session['INIT_DICT']['User']['UserName']  # session初始化，User.UserName
    to = req.POST.get('to')  # @dfb23e0da382f51746575a038323834a
    msg = req.POST.get('msg')  # asdfasdfasdf

    # session Ticket
    # session Cookie
    ticket_dict = req.session['TICKED_DICT']
    ctime = int(time.time() * 1000)
    post_data = req.session['POST_DATA']
    add_data = {
        "Msg": {
            "ClientMsgId": ctime,
            "LocalID": ctime,
            "FromUserName": current_user,
            "ToUserName": to,
            "Content": msg,
            "Type": 1
        },
        "Scene": 0
    }
    post_data.update(add_data)

    url = "{0}/webwxsendmsg?pass_ticket={1}".format(settings.MAIN_URL, ticket_dict['pass_ticket'])
    # 以json类型发送数据，需使用ensure_ascii和encode处理中文消息
    res = requests.post(url=url, data=json.dumps(post_data, ensure_ascii=False).encode('utf-8'),
                        headers={'Content-Type': "application/json", 'User-Agent': settings.USER_AGENT})
    # print(res.text)
    return HttpResponse('...')


def get_msg(req):
    """
    长轮询获取消息
    :param req:
    :return:
    """
    # 检查是否有消息到来
    ctime = int(time.time() * 1000)
    ticket_dict = req.session['TICKED_DICT']
    check_msg_url = "https://webpush.wx.qq.com/cgi-bin/mmwebwx-bin/synccheck"

    cookies = {}
    cookies.update(req.session['LOGIN_COOKIE'])
    cookies.update(req.session['TICKED_COOKIE'])

    synckey_dict = req.session['INIT_DICT']['SyncKey']
    synckey_list = []
    for item in synckey_dict['List']:
        tmp = "{}_{}".format(item['Key'], item['Val'])
        synckey_list.append(tmp)
    synckey = "|".join(synckey_list)

    post_data = req.session['POST_DATA']
    params = {
        'r': ctime,
        "deviceid": post_data['BaseRequest']["DeviceID"],
        'sid': post_data['BaseRequest']["Sid"],
        'uin': post_data['BaseRequest']["Uin"],
        'skey': post_data['BaseRequest']["Skey"],
        '_': ctime,
        'synckey': synckey
    }

    r1 = requests.get(
        url=check_msg_url,
        params=params,
        cookies=cookies,
        headers=headers
    )
    # print(r1.text)
    # 没有消息的返回值特征
    if '{retcode:"0",selector:"0"}' in r1.text:
        return HttpResponse('...')

    # 有消息，获取消息
    base_get_msg_url = "{0}/webwxsync?sid={1}&skey={2}&lang=zh_CN&pass_ticket={3}"
    get_msg_url = base_get_msg_url.format(settings.MAIN_URL,
                                          ticket_dict['wxsid'], ticket_dict['skey'], ticket_dict['pass_ticket'])

    post_data['SyncKey'] = req.session['INIT_DICT']['SyncKey']
    r2 = requests.post(url=get_msg_url, json=post_data, cookies=cookies, headers=headers)
    r2.encoding = 'utf-8'
    # 接受到消息： synckey会改变
    msg_dict = json.loads(r2.text)
    # print(msg_dict)
    for msg in msg_dict['AddMsgList']:
        print('您有新消息到来：', msg['Content'])
    init_dict = req.session['INIT_DICT']
    init_dict['SyncKey'] = msg_dict['SyncKey']
    req.session['INIT_DICT'] = init_dict

    return HttpResponse('...')
