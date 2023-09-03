#! /usr/bin/env python3
# -*- coding: utf-8 -*- 
#
# SPDX-FileCopyrightText: (c) 2020-2021 CokeMine & Its repository contributors
# SPDX-FileCopyrightText: (c) 2021 A beam of light
#
# SPDX-License-Identifier: GPL-3.0-or-later
#

"""
euserv auto-renew script
       v2021.09.30
* Captcha automatic recognition using TrueCaptcha API
* Email notification
* Add login failure retry mechanism
* reformat log info
       v2021.11.06
* Receive renew PIN(6-digits) using mailparser parsed data download url
  workflow: auto-forward your EUserv PIN email to your mailparser inbox 
  -> parsing PIN via mailparser 
  -> get PIN from mailparser
* Update kc2_security_password_get_token request
"""

import os
import re
import json
import time
import base64

from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from smtplib import SMTP_SSL, SMTPDataError

import requests
from bs4 import BeautifulSoup

# 多个账户请使用空格隔开
USERNAME = os.environ["USERNAME"]  # 用户名或邮箱
PASSWORD = os.environ["PASSWORD"]  # 密码

# default value is TrueCaptcha demo credential,
# you can use your own credential via set environment variables:
# TRUECAPTCHA_USERID and TRUECAPTCHA_APIKEY
# demo: https://apitruecaptcha.org/demo
# demo2: https://apitruecaptcha.org/demo2
# demo apikey also has a limit of 100 times per day
# {
# 'error': '101.0 above free usage limit 100 per day and no balance',
# 'requestId': '7690c065-70e0-4757-839b-5fd8381e65c7'
# }
TRUECAPTCHA_USERID = os.environ.get("TRUECAPTCHA_USERID", "arun56")
TRUECAPTCHA_APIKEY = os.environ.get("TRUECAPTCHA_APIKEY", "wMjXmBIcHcdYqO2RrsVN")

# Extract key data from your emails, automatically. https://mailparser.io 
# 30 Emails/Month, 10 inboxes and unlimited downloads for free.
# 多个mailparser下载链接id请使用空格隔开, 顺序与 EUserv 账号/邮箱一一对应
MAILPARSER_DOWNLOAD_URL_ID = os.environ["MAILPARSER_DOWNLOAD_URL_ID"]
# mailparser.io parsed data download base url
MAILPARSER_DOWNLOAD_BASE_URL = "https://files.mailparser.io/d/"

# Telegram Bot Push https://core.telegram.org/bots/api#authorizing-your-bot
TG_BOT_TOKEN = ""  # 通过 @BotFather 申请获得，示例：1077xxx4424:AAFjv0FcqxxxxxxgEMGfi22B4yh15R5uw
TG_USER_ID = ""  # 用户、群组或频道 ID，示例：129xxx206
TG_API_HOST = "https://api.telegram.org"  # 自建 API 反代地址，供网络环境无法访问时使用，网络正常则保持默认

# Email notification
RECEIVER_EMAIL = os.environ.get("RECEIVER_EMAIL", "")
YD_EMAIL = os.environ.get("YD_EMAIL", "")
YD_APP_PWD = os.environ.get("YD_APP_PWD", "")  # yandex mail 使用第三方 APP 授权码

# Magic internet access
PROXIES = {"http": "http://127.0.0.1:10808", "https": "http://127.0.0.1:10808"}

# Maximum number of login retry
LOGIN_MAX_RETRY_COUNT = 5

# Waiting time of receiving PIN, units are seconds.
WAITING_TIME_OF_PIN = 15

# options: True or False
CHECK_CAPTCHA_SOLVER_USAGE = True

user_agent = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/95.0.4638.69 Safari/537.36"
)

desp = ""  # 空值


def log(info: str):
    print(info)
    global desp
    desp = desp + info + "\n\n"


def login_retry(*args, **kwargs):
    def wrapper(func):
        def inner(username, password):
            ret, ret_session = func(username, password)
            max_retry = kwargs.get("max_retry")
            # default retry 3 times
            if not max_retry:
                max_retry = 3
            number = 0
            if ret == "-1":
                while number < max_retry:
                    number += 1
                    if number > 1:
                        log("[EUserv] Login tried the {}th time".format(number))
                    sess_id, session = func(username, password)
                    if sess_id != "-1":
                        return sess_id, session
                    else:
                        if number == max_retry:
                            return sess_id, session
            else:
                return ret, ret_session

        return inner

    return wrapper

def get_pin_from_mailparser(url_id: str) -> str:
    response = requests.get(
        f"{MAILPARSER_DOWNLOAD_BASE_URL}{url_id}",
        # Mailparser parsed data download using Basic Authentication.
        # auth=("<your mailparser username>", "<your mailparser password>")
    )
    pin = response.json()[0]["pin"]
    return pin


@login_retry(max_retry=LOGIN_MAX_RETRY_COUNT)
def login(username: str, password: str) -> (str, requests.session):
    headers = {"user-agent": user_agent, "origin": "https://www.euserv.com"}
    url = "https://support.euserv.com/index.iphp"
    captcha_image_url = "https://support.euserv.com/securimage_show.php"
    session = requests.Session()
       
    sess = session.get(url, headers=headers)
    sess_id = re.findall("PHPSESSID=(\\w{10,100});", str(sess.headers))[0]
       
    log("[EUserv] sess_id：" + sess_id)

    # visit png
    logo_png_url = "https://support.euserv.com/pic/logo_small.png"
    sess = session.get(logo_png_url, headers=headers)
  
    # 登录url
    url = "https://support.euserv.com/index.iphp?sess_id=" + sess_id
       
    log("[EUserv] 正在登录：" + url) 

    login_data = {
        "email": username,
        "password": password,
        "form_selected_language": "en",
        "Submit": "Login",
        "subaction": "login",
        "sess_id": sess_id,
    }
    f = session.post(url, headers=headers, data=login_data)
    f.raise_for_status()   
       
    if (
        f.text.find("Hello") == -1
        and f.text.find("Confirm or change your customer data here") == -1
    ):
        if (
            f.text.find(
                "To finish the login process please solve the following captcha."
            )
            == -1
        ):
            return "-1", session
        else:
            f2 = session.post(
                url,
                headers=headers,
                data={
                    "subaction": "login",
                    "sess_id": sess_id,
                },
            )
            if (
                f2.text.find(
                    "To finish the login process please solve the following captcha."
                )
                == -1
            ):
                log("[Captcha Solver] 验证通过")
                return sess_id, session
            else:
                log("[Captcha Solver] 验证失败")
                return "-1", session

    else:
        return sess_id, session


def get_servers(sess_id: str, session: requests.session) -> {}:
    d = {}
    url = "https://support.euserv.com/index.iphp?sess_id=" + sess_id
    headers = {"user-agent": user_agent, "origin": "https://www.euserv.com"}
    f = session.get(url=url, headers=headers)
    f.raise_for_status()
    soup = BeautifulSoup(f.text, "html.parser")
    for tr in soup.select(
        "#kc2_order_customer_orders_tab_content_1 .kc2_order_table.kc2_content_table tr"
    ):
        server_id = tr.select(".td-z1-sp1-kc")
        if not len(server_id) == 1:
            continue
        flag = (
            True
            if tr.select(".td-z1-sp2-kc .kc2_order_action_container")[0]
            .get_text()
            .find("Contract extension possible from")
            == -1
            else False
        )
        d[server_id[0].get_text()] = flag
    return d


def renew(
    sess_id: str, session: requests.session, password: str, order_id: str, mailparser_dl_url_id: str
) -> bool:
    url = "https://support.euserv.com/index.iphp"
    headers = {
        "user-agent": user_agent,
        "Host": "support.euserv.com",
        "origin": "https://support.euserv.com",
        "Referer": "https://support.euserv.com/index.iphp",
    }
    data = {
        "Submit": "Extend contract",
        "sess_id": sess_id,
        "ord_no": order_id,
        "subaction": "choose_order",
        "choose_order_subaction": "show_contract_details",
    }
    session.post(url, headers=headers, data=data)

    # pop up 'Security Check' window, it will trigger 'send PIN' automatically.
    session.post(
        url,
        headers=headers,
        data={
            "sess_id": sess_id,
            "subaction": "show_kc2_security_password_dialog",
            "prefix": "kc2_customer_contract_details_extend_contract_",
            "type": "1",
        },
    )

    # # trigger 'Send new PIN to your Email-Address' (optional),
    # new_pin = session.post(url, headers=headers, data={
    #     "sess_id": sess_id,
    #     "subaction": "kc2_security_password_send_pin",
    #     "ident": f"kc2_customer_contract_details_extend_contract_{order_id}"
    # })
    # if not json.loads(new_pin.text)["rc"] == "100":
    #     print("new PIN Not Sended")
    #     return False

    # sleep WAITING_TIME_OF_PIN seconds waiting for mailparser email parsed PIN
    time.sleep(WAITING_TIME_OF_PIN)
    pin = get_pin_from_mailparser(mailparser_dl_url_id)
    log(f"[MailParser] PIN: {pin}")

    # using PIN instead of password to get token
    data = {
        "auth": pin,
        "sess_id": sess_id,
        "subaction": "kc2_security_password_get_token",
        "prefix": "kc2_customer_contract_details_extend_contract_",
        "type": 1,
        "ident": f"kc2_customer_contract_details_extend_contract_{order_id}",
    }
    f = session.post(url, headers=headers, data=data)
    f.raise_for_status()
    if not json.loads(f.text)["rs"] == "success":
        return False
    token = json.loads(f.text)["token"]["value"]
    data = {
        "sess_id": sess_id,
        "ord_id": order_id,
        "subaction": "kc2_customer_contract_details_extend_contract_term",
        "token": token,
    }
    session.post(url, headers=headers, data=data)
    time.sleep(5)
    return True


def check(sess_id: str, session: requests.session):
    print("Checking.......")
    d = get_servers(sess_id, session)
    flag = True
    for key, val in d.items():
        if val:
            flag = False
            log("[EUserv] ServerID: %s Renew Failed!" % key)

    if flag:
        log("[EUserv] ALL Work Done! Enjoy~")


# Telegram Bot Push https://core.telegram.org/bots/api#authorizing-your-bot
def telegram():
    data = (("chat_id", TG_USER_ID), ("text", "EUserv续费日志\n\n" + desp))
    response = requests.post(
        TG_API_HOST + "/bot" + TG_BOT_TOKEN + "/sendMessage", data=data
    )
    if response.status_code != 200:
        print("Telegram Bot 推送失败")
    else:
        print("Telegram Bot 推送成功")


def send_mail_by_yandex(
    to_email, from_email, subject, text, files, sender_email, sender_password
):
    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = to_email
    msg.attach(MIMEText(text, _charset="utf-8"))
    if files is not None:
        for file in files:
            file_name, file_content = file
            # print(file_name)
            part = MIMEApplication(file_content)
            part.add_header(
                "Content-Disposition", "attachment", filename=("gb18030", "", file_name)
            )
            msg.attach(part)
    s = SMTP_SSL("smtp.yandex.ru", 465)
    s.login(sender_email, sender_password)
    try:
        s.sendmail(msg["From"], msg["To"], msg.as_string())
    except SMTPDataError as e:
        raise e
    finally:
        s.close()


def email():
    msg = "EUserv 续费日志\n\n" + desp
    try:
        send_mail_by_yandex(
            RECEIVER_EMAIL, YD_EMAIL, "EUserv 续费日志", msg, None, YD_EMAIL, YD_APP_PWD
        )
        print("eMail 推送成功")
    except requests.exceptions.RequestException as e:
        print(str(e))
        print("eMail 推送失败")
    except SMTPDataError as e1:
        print(str(e1))
        print("eMail 推送失败")


if __name__ == "__main__":
    if not USERNAME or not PASSWORD:
        log("[EUserv] 你没有添加任何账户")
        exit(1)
    user_list = USERNAME.strip().split()
    passwd_list = PASSWORD.strip().split()
    mailparser_dl_url_id_list = MAILPARSER_DOWNLOAD_URL_ID.strip().split()
    if len(user_list) != len(passwd_list):
        log("[EUserv] The number of usernames and passwords do not match!")
        exit(1)
    if len(mailparser_dl_url_id_list) != len(user_list):
        log("[Mailparser] The number of mailparser_dl_url_ids and usernames do not match!")
        exit(1)
    for i in range(len(user_list)):
        print("*" * 30)
        log("[EUserv] 正在续费第 %d 个账号" % (i + 1))
           
        log("[EUserv] 账号名：" + user_list[i])

        sessid, s = login(user_list[i], passwd_list[i])
        if sessid == "-1":
            log("[EUserv] 第 %d 个账号登陆失败，请检查登录信息" % (i + 1))
            continue
        SERVERS = get_servers(sessid, s)
        log("[EUserv] 检测到第 {} 个账号有 {} 台 VPS，正在尝试续期".format(i + 1, len(SERVERS)))
        for k, v in SERVERS.items():
            if v:
                if not renew(sessid, s, passwd_list[i], k, mailparser_dl_url_id_list[i]):
                    log("[EUserv] ServerID: %s Renew Error!" % k)
                else:
                    log("[EUserv] ServerID: %s has been successfully renewed!" % k)
            else:
                log("[EUserv] ServerID: %s does not need to be renewed" % k)
        time.sleep(15)
        check(sessid, s)
        time.sleep(5)

    TG_BOT_TOKEN and TG_USER_ID and TG_API_HOST and telegram()
    RECEIVER_EMAIL and YD_EMAIL and YD_APP_PWD and email()

    print("*" * 30)
