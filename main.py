import requests
import json
import os
import time
from datetime import datetime, timedelta
import logging
import random
import argparse
import asyncio
from typing import Dict, List, Optional
from dingtalkchatbot.chatbot import DingtalkChatbot

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 调试模式
IS_DEBUG = os.getenv('IS_DEBUG', 'false').lower() == 'true'

# 常量
BASE_URL = "https://gw2c-hw-open.longfor.com"
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf2540615) XWEB/16041"
]
USER_AGENT = random.choice(USER_AGENTS) # 保持 USER_AGENT 变量以便向后兼容

# 默认请求头
DEFAULT_HEADERS = {
    'User-Agent': random.choice(USER_AGENTS),
    'Origin': 'https://longzhu.longfor.com',
    'Referer': 'https://longzhu.longfor.com/',
    'X-Gaia-Api-Key': 'c06753f1-3e68-437d-b592-b94656ea5517'
}

# 通知消息
notify_msg: List[str] = []

# 助力任务状态文件
ASSIST_STATUS_FILE = 'assist_status.json'


# 账户配置信息 - 从JSON文件读取
def get_cookies() -> (Optional[List[Dict]], Optional[List[Dict]]):
    """从JSON文件读取账户和助力组配置"""
    try:
        with open('lhtj_data.json', 'r', encoding='utf-8') as f:
            config_data = json.load(f)
        
        accounts_config = config_data.get("accounts", [])
        assist_groups = config_data.get("assist_groups", [])
        # 补充环境变量
        for k in accounts_config[0]:
            if os.getenv(k):
                v = os.getenv(k)
                accounts_config[0][k] = v
        for k in assist_groups[0]:
            if os.getenv(k):
                v = os.getenv(k)
                assist_groups[0][k] = v

        # 固定配置模板
        fixed_config = {
            "x-lf-channel": "C2",
            "x-lf-bu-code": "C20400",
            "x-lf-dxrisk-source": "5",
            "x-gaia-api-key": "c06753f1-3e68-437d-b592-b94656ea5517",
            "x-gaia-api-key-lottery": "2f9e3889-91d9-4684-8ff5-24d881438eaf",
            "x-lf-dxrisk-captcha-token": "undefined",
            "user-agent": random.choice(USER_AGENTS),
            "origin-signin": "https://longzhu.longfor.com",
            "referer-signin": "https://longzhu.longfor.com/",
            "origin-lottery": "https://llt.longfor.com",
            "referer-lottery": "https://llt.longfor.com/",
            "content-type": "application/json;charset=UTF-8"
        }

        # 合并动态配置和固定配置
        full_accounts_config = []
        for account_config in accounts_config:
            merged_config = {**fixed_config, **account_config}
            full_accounts_config.append(merged_config)

        return full_accounts_config, assist_groups
    except Exception as e:
        logger.error(f"读取配置文件失败: {e}")
        return None, None

def debug(obj, label: str = "debug"):
    """调试日志"""
    if IS_DEBUG:
        logger.debug(f"\n-----------{label}------------\n{json.dumps(obj, indent=2, ensure_ascii=False)}\n-----------{label}------------\n")

def double_log(msg: str):
    """同时记录日志和通知消息"""
    logger.info(msg)
    notify_msg.append(msg)

def load_assist_status() -> Dict:
    """加载助力任务状态"""
    try:
        with open(ASSIST_STATUS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # 如果文件不存在，或者文件为空/格式错误，都返回空字典
        return {}
    except Exception as e:
        logger.error(f"加载助力状态时发生未知错误: {e}")
        return {}

def save_assist_status(status: Dict):
    """保存助力任务状态"""
    try:
        with open(ASSIST_STATUS_FILE, 'w', encoding='utf-8') as f:
            json.dump(status, f, ensure_ascii=False, indent=2)
        logger.info("助力状态保存成功")
    except Exception as e:
        logger.error(f"保存助力状态失败: {e}")

def should_launch_assist(account_id: str, new_end_time: Optional[str]) -> bool:
    """检查是否应该基于任务结束时间发起新的助力任务"""
    if not new_end_time:
        logger.warning(f"账号 {account_id} 未能获取到新任务的 end_time，无法判断是否需要发起助力。")
        return False

    status = load_assist_status()
    account_status = status.get(account_id, {})
    last_task_end_time = account_status.get('last_task_end_time')

    if not last_task_end_time:
        logger.info(f"账号 {account_id} 从未记录过助力任务，需要发起新助力。")
        return True

    if str(last_task_end_time) != str(new_end_time):
        logger.info(f"账号 {account_id} 的任务 end_time 已变更 (旧: {last_task_end_time}, 新: {new_end_time})，需要发起新助力。")
        return True
    else:
        logger.info(f"账号 {account_id} 的任务 end_time ({new_end_time}) 未变更，无需发起新助力。")
        return False

def record_assist_launch(account_id: str, launch_data: Dict, end_time: str):
    """记录助力任务发起，并保存任务的 end_time"""
    status = load_assist_status()

    if account_id not in status:
        status[account_id] = {}

    status[account_id].update({
        'last_launch_time': datetime.now().isoformat(),
        'user_task_no': launch_data.get('user_task_no', ''),
        'invite_code': launch_data.get('invite_code', ''),
        'target': launch_data.get('target', 0),
        'invite_reward_num': launch_data.get('invite_reward_num', 0),
        'last_task_end_time': end_time  # 新增字段
    })

    save_assist_status(status)
    logger.info(f"记录账号 {account_id} 助力任务发起状态 (end_time: {end_time})")


def is_same_week(date1: datetime, date2: datetime) -> bool:
    """检查两个日期是否在同一周（周一为一周的开始）"""
    return date1.isocalendar()[:2] == date2.isocalendar()[:2]

def record_follower_assist(master_account_id: str, follower_account_id: str):
    """记录从账号的助力信息"""
    status = load_assist_status()
    
    # 使用 setdefault 确保 followers_assisted 键存在
    followers_assisted = status.setdefault(master_account_id, {}).setdefault('followers_assisted', {})
    
    # 记录助力时间
    followers_assisted[follower_account_id] = datetime.now().isoformat()
    
    save_assist_status(status)
    logger.info(f"已记录从账号 {follower_account_id} 对主账号 {master_account_id} 的助力")


async def fetch(url: str, headers: Dict, method: str = 'POST', data: Optional[Dict] = None, timeout: int = 10) -> Dict:
    """通用 HTTP 请求"""
    try:
        headers = {k.lower(): v for k, v in headers.items()}  # 统一小写键名
        if method.upper() == 'POST':
            response = requests.post(url, headers=headers, json=data, timeout=timeout)
        else:
            response = requests.get(url, headers=headers, params=data, timeout=timeout)
        
        response.raise_for_status()
        res = response.json()
        debug(res, url.split('/')[-1])
        
        if 'message' in res and '登录已过期' in res['message'] or '用户未登录' in res['message']:
            raise Exception("用户需要去登录")
        
        return res
    except Exception as e:
        logger.error(f"请求失败: {e}")
        return {}

async def signin(user: Dict) -> int:
    """每日签到"""
    try:
        url = f"{BASE_URL}/lmarketing-task-api-mvc-prod/openapi/task/v1/signature/clock"
        headers = {
            'User-Agent': user['user-agent'],
            'Origin': user['origin-signin'],
            'Referer': user['referer-signin'],
            'X-LF-DXRisk-Source': user['x-lf-dxrisk-source'],
            'X-LF-Bu-Code': user['x-lf-bu-code'],
            'X-GAIA-API-KEY': user['x-gaia-api-key'],
            'X-LF-UserToken': user['x-lf-usertoken'],
            'X-LF-Channel': user['x-lf-channel'],
            'X-LF-DXRisk-Token': user['x-lf-dxrisk-token'],
            'token': user['token'],
            'Cookie': user['cookie'],
            'Content-Type': user['content-type']
        }
        data = {"activity_no": "11111111111686241863606037740000"}
        res = await fetch(url, headers, 'POST', data)
        
        reward_num = res.get('data', {}).get('reward_info', [{}])[0].get('reward_num', 0) if res.get('data', {}).get('is_popup') == 1 else 0
        status = "✅ 每日签到: 成功, 获得" + str(reward_num) + "分" if res.get('data', {}).get('is_popup') == 1 else "⛔️ 每日签到: 今日已签到"
        double_log(status)
        return reward_num
    except Exception as e:
        double_log(f"⛔️ 每日签到失败: {e}")
        return 0

async def lottery_signin(user: Dict):
    """抽奖签到"""
    try:
        activity_info = await get_lottery_activity_info(user)
        if not activity_info:
            logger.error("获取抽奖活动ID失败")
            double_log("⛔️ 抽奖签到: 获取抽奖活动ID失败")
            return 0, None

        url = f"{BASE_URL}/llt-gateway-prod/api/v1/activity/auth/lottery/sign"
        headers = {
            'User-Agent': user['user-agent'],
            'Origin': user['origin-lottery'],
            'Referer': user['referer-lottery'],
            'x-gaia-api-key': user['x-gaia-api-key-lottery'],
            'bucode': user['x-lf-bu-code'],
            'authtoken': user['token'],
            'channel': user['x-lf-channel'],
            'Content-Type': user['content-type'],
            'Cookie': user['cookie'],
            'X-LF-DXRisk-Source': user['x-lf-dxrisk-source'],
            'X-LF-DXRisk-Token': user['x-lf-dxrisk-token']
        }
        data = {
            'component_no': activity_info['component_no'],
            'activity_no': activity_info['activity_no']
        }
        res = await fetch(url, headers, 'POST', data)
        
        chance = res.get('data', {}).get('chance', 0)
        status = f"✅ 抽奖签到: 成功, 获得{chance}次抽奖机会" if res.get('code') == '0000' else f"⛔️ 抽奖签到: {res.get('message', '未知错误')}"
        double_log(status)
        return chance, activity_info
    except Exception as e:
        double_log(f"⛔️ 抽奖签到失败: {e}")
        return 0, None

async def lottery_clock(user: Dict, activity_info: Dict):
    """抽奖"""
    if not activity_info:
        logger.error("抽奖失败: activity_info 为 None")
        return
        
    try:
        url = f"{BASE_URL}/llt-gateway-prod/api/v1/activity/auth/lottery/click"
        headers = {
            'User-Agent': user['user-agent'],
            'Origin': user['origin-lottery'],
            'Referer': user['referer-lottery'],
            'x-gaia-api-key': user['x-gaia-api-key-lottery'],
            'bucode': user['x-lf-bu-code'],
            'authtoken': user['token'],
            'channel': user['x-lf-channel'],
            'Content-Type': 'application/json',
            'Cookie': user['cookie'],
            'X-LF-DXRisk-Source': user['x-lf-dxrisk-source'],
            'X-LF-DXRisk-Token': user['x-lf-dxrisk-token']
        }
        data = {
            "component_no": activity_info.get('component_no'),
            "activity_no": activity_info.get('activity_no'),
            "batch_no": ""
        }
        res = await fetch(url, headers, 'POST', data)

        reward_info = ""
        if res.get('code') == '0000':
            reward_type = res.get('data', {}).get('reward_type', 0)
            reward_num = res.get('data', {}).get('reward_num', 0)
            if reward_type > 0 and reward_num > 0:
                reward_info = f", 获得奖励类型: {reward_type}, 数量: {reward_num}"
            status = f"✅ 抽奖成功{reward_info}"
        else:
            status = f"⛔️ 抽奖: {res.get('message', '未知错误')}"
        double_log(status)
    except Exception as e:
        double_log(f"⛔️ 抽奖失败: {e}")

async def get_assist_info(user: Dict, sub_task_no: str, component_no: str, activity_no: str = "AP25O060F9O7SX1C"):
    """获取助力任务详情"""
    try:
        url = f"{BASE_URL}/llt-gateway-prod/api/v1/activity/common/assist/expand-info"
        headers = {
            'User-Agent': user['user-agent'],
            'Origin': user['origin-lottery'],
            'Referer': user['referer-lottery'],
            'x-gaia-api-key': user['x-gaia-api-key-lottery'],
            'bucode': user['x-lf-bu-code'],
            'authtoken': user['token'],
            'channel': user['x-lf-channel'],
            'Content-Type': 'application/json',
            'Cookie': user['cookie']
        }
        data = {
            "component_no": component_no,
            "activity_no": activity_no,
            "sub_task_no": sub_task_no
        }
        res = await fetch(url, headers, 'POST', data)

        if res.get('code') == '0000':
            assist_data = res.get('data', {})
            target = assist_data.get('target', 0)
            helper_num = assist_data.get('helper_num', 0)
            double_log(f"✅ 获取助力详情成功, 目标:{target}人, 当前:{helper_num}人")
            return assist_data
        else:
            double_log(f"⛔️ 获取助力详情失败: {res.get('message', '未知错误')}")
            return {}
    except Exception as e:
        double_log(f"⛔️ 获取助力详情失败: {e}")
        return {}

async def launch_assist(user: Dict, sub_task_no: str, component_no: str, activity_no: str = "AP25O060F9O7SX1C"):
    """发起助力任务"""
    try:
        url = f"{BASE_URL}/llt-gateway-prod/api/v1/activity/auth/assist/invite"
        headers = {
            'User-Agent': user['user-agent'],
            'Origin': user['origin-lottery'],
            'Referer': user['referer-lottery'],
            'x-gaia-api-key': user['x-gaia-api-key-lottery'],
            'bucode': user['x-lf-bu-code'],
            'authtoken': user['token'],
            'channel': user['x-lf-channel'],
            'Content-Type': 'application/json',
            'Cookie': user['cookie'],
            'X-LF-DXRisk-Source': user['x-lf-dxrisk-source'],
            'X-LF-DXRisk-Token': user['x-lf-dxrisk-token']
        }
        data = {
            "sub_task_no": sub_task_no,
            "component_no": component_no,
            "activity_no": activity_no
        }
        res = await fetch(url, headers, 'POST', data)

        if res.get('code') == '0000':
            launch_data = res.get('data', {})
            user_task_no = launch_data.get('user_task_no', '')
            invite_code = launch_data.get('invite_code', '')
            invite_reward_num = launch_data.get('invite_reward_num', 0)
            target = launch_data.get('target', 0)
            double_log(f"✅ 发起助力成功, 任务编号:{user_task_no}, 邀请码:{invite_code}, 奖励:{invite_reward_num}, 目标:{target}人")
            return launch_data
        else:
            msg = res.get('message', '未知错误')
            double_log(f"⛔️ 发起助力失败: {msg}")
            return {"error": True, "message": msg}
    except Exception as e:
        double_log(f"⛔️ 发起助力失败: {e}")
        return {"error": True, "message": str(e)}

async def assist_help(user: Dict, user_task_no: str, invite_code: str, activity_no: str = "AP25O060F9O7SX1C", **kwargs):
    """参与助力"""
    try:
        url = f"{BASE_URL}/llt-gateway-prod/api/v1/activity/auth/assist/help"
        headers = {
            'User-Agent': user['user-agent'],
            'Origin': user['origin-lottery'],
            'Referer': user['referer-lottery'],
            'x-gaia-api-key': user['x-gaia-api-key-lottery'],
            'bucode': user['x-lf-bu-code'],
            'authtoken': user['token'],
            'channel': user['x-lf-channel'],
            'Content-Type': 'application/json',
            'Cookie': user['cookie'],
            'X-LF-DXRisk-Source': user['x-lf-dxrisk-source'],
            'X-LF-DXRisk-Token': user['x-lf-dxrisk-token']
        }
        data = {
            "sub_task_no": "null",
            "user_task_no": user_task_no,
            "invite_code": invite_code,
            "activity_no": activity_no
        }
        res = await fetch(url, headers, 'POST', data)

        if res.get('code') == '0000':
            help_status = res.get('data', {}).get('help_status', 0)
            status = f"✅ 助力成功, 状态: {help_status}" if help_status == 10 else f"⚠️ 助力完成, 状态: {help_status}"
        else:
            status = f"⛔️ 助力失败: {res.get('message', '未知错误')}"
        double_log(status)
        return res.get('code') == '0000'
    except Exception as e:
        double_log(f"⛔️ 助力失败: {e}")
        return False

async def get_user_info(user: Dict) -> Dict:
    """查询用户信息"""
    try:
        url = "https://longzhu-api.longfor.com/lmember-member-open-api-prod/api/member/v1/mine-info"
        headers = {
            'User-Agent': random.choice(USER_AGENTS),
            'Referer': 'https://servicewechat.com/wx50282644351869da/424/page-frame.html',
            'token': user['token'],
            'X-Gaia-Api-Key': 'd1eb973c-64ec-4dbe-b23b-22c8117c4e8e'
        }
        data = {
            "channel": user['x-lf-channel'],
            "bu_code": user['x-lf-bu-code'],
            "token": user['token']
        }
        res = await fetch(url, headers, 'POST', data)
        
        growth_value = res.get('data', {}).get('growth_value', 0)
        status = f"🎉 您当前成长值: {growth_value}" if res.get('code') == '0000' else f"⛔️ {res.get('message', '查询失败')}"
        double_log(status)
        return res.get('data', {})
    except Exception as e:
        double_log(f"⛔️ 查询用户信息失败: {e}")
        return {}

async def get_balance(user: Dict) -> Dict:
    """查询珑珠余额"""
    try:
        url = "https://longzhu-api.longfor.com/lmember-member-open-api-prod/api/member/v1/balance"
        headers = {
            'User-Agent': random.choice(USER_AGENTS),
            'Referer': 'https://servicewechat.com/wx50282644351869da/424/page-frame.html',
            'token': user['token'],
            'X-Gaia-Api-Key': 'd1eb973c-64ec-4dbe-b23b-22c8117c4e8e'
        }
        data = {
            "channel": user['x-lf-channel'],
            "bu_code": user['x-lf-bu-code'],
            "token": user['token']
        }
        res = await fetch(url, headers, 'POST', data)
        
        balance = res.get('data', {}).get('balance', 0)
        expiring_lz = res.get('data', {}).get('expiring_lz', 0)
        status = f"🎉 您当前珑珠: {balance}, 即将过期: {expiring_lz}" if res.get('code') == '0000' else f"⛔️ {res.get('message', '查询失败')}"
        double_log(status)
        return res.get('data', {})
    except Exception as e:
        double_log(f"⛔️ 查询用户珑珠失败: {e}")
        return {}

async def get_active_assist_task(user: Dict) -> List[Dict[str, str]]:
    """
    重构后的函数：动态获取所有当前有效的助力任务。
    1. 调用 /page/info 获取页面组件信息，提取所有 'assistcom' 组件的 component_no。
    2. 对每个 component_no，调用 /common/task/list 获取其任务列表。
    3. 从所有任务列表中找到当前时间有效的所有任务，并返回它们的详细信息。
    """
    try:
        # --- 步骤 1: 获取页面信息以提取所有相关 component_no ---
        page_info_url = f"{BASE_URL}/llt-gateway-prod/api/v1/page/info"
        headers = {
            'User-Agent': user['user-agent'],
            'Origin': user['origin-lottery'],
            'Referer': user['referer-lottery'],
            'x-gaia-api-key': user['x-gaia-api-key-lottery'],
            'bucode': user['x-lf-bu-code'],
            'authtoken': user['token'],
            'channel': user['x-lf-channel'],
            'Content-Type': 'application/json',
            'Cookie': user['cookie']
        }
        page_info_params = {
            "activityNo": "AP25O060F9O7SX1C",
            "pageNo": "PY10R18N57K8RRCL"
        }
        page_res = await fetch(page_info_url, headers, 'GET', page_info_params)

        component_nos = []
        activity_no = "AP25O060F9O7SX1C"

        if page_res.get('code') == '0000' and page_res.get('data', {}).get('info'):
            page_info = json.loads(page_res['data']['info'])
            for component in page_info.get('list', []):
                if component.get('comName') == 'assistcom':
                    component_no = component.get('data', {}).get('component_no')
                    if component_no:
                        component_nos.append(component_no)
        
        if not component_nos:
            logger.error(f"获取页面信息成功，但未找到任何 'assistcom' 组件。")
            return []

        # --- 步骤 2 & 3: 遍历 component_no，获取并筛选有效任务 ---
        active_tasks = []
        now_ts = datetime.now().timestamp()

        for component_no in component_nos:
            task_list_url = f"{BASE_URL}/llt-gateway-prod/api/v1/activity/common/task/list"
            task_list_params = {
                "component_no": component_no,
                "activity_no": activity_no
            }
            task_res = await fetch(task_list_url, headers, 'GET', task_list_params)

            if task_res.get('code') == '0000' and task_res.get('data'):
                task_list = task_res.get('data', [])
                for task in task_list:
                    start_time_str = task.get('start_time')
                    end_time_str = task.get('end_time')

                    if start_time_str and end_time_str:
                        try:
                            start_ts = int(start_time_str) / 1000
                            end_ts = int(end_time_str) / 1000

                            if start_ts <= now_ts <= end_ts:
                                sub_task_no = task.get('sub_task_no')
                                if sub_task_no:
                                    task_info = {
                                        'component_no': component_no,
                                        'sub_task_no': sub_task_no,
                                        'end_time': end_time_str,
                                        'title': task.get('title', '未知任务')
                                    }
                                    active_tasks.append(task_info)
                                    logger.info(f"找到当前有效助力任务: {json.dumps(task_info, ensure_ascii=False)}")
                        except (ValueError, TypeError) as e:
                            logger.error(f"解析任务时间戳 '{start_time_str}' 或 '{end_time_str}' 时出错: {e}")
                            continue
            else:
                logger.error(f"为 component_no {component_no} 调用任务列表API失败: {task_res.get('message', '未知错误')}")
        
        if not active_tasks:
            logger.warning("在所有助力组件中均未找到当前时间有效的任务。")

        return active_tasks

    except Exception as e:
        logger.error(f"动态获取助力任务时发生异常: {e}")
        return []

async def get_lottery_activity_info(user: Dict) -> Optional[Dict[str, str]]:
    """获取抽奖活动信息 (component_no 和 activity_no)"""
    try:
        url = f"{BASE_URL}/llt-gateway-prod/api/v1/page/info"
        headers = {
            'User-Agent': user['user-agent'],
            'Origin': user['origin-lottery'],
            'Referer': user['referer-lottery'],
            'x-gaia-api-key': user['x-gaia-api-key-lottery'],
            'bucode': user['x-lf-bu-code'],
            'authtoken': user['token'],
            'channel': user['x-lf-channel'],
            'Content-Type': 'application/json',
            'Cookie': user['cookie']
        }
        params = {
            'activityNo': 'AP25Z07390KXCWDP',
            'pageNo': 'PP11I27P15H4JYOY'
        }
        res = await fetch(url, headers, 'GET', params)

        if res.get('code') == '0000' and res.get('data'):
            info_str = res['data'].get('info')
            if not info_str:
                logger.error("API响应中缺少 'info' 字段")
                return None
            
            try:
                info_data = json.loads(info_str)
            except json.JSONDecodeError:
                logger.error("解析 'info' 字段 (JSON字符串) 失败")
                return None

            activity_no = res['data'].get('activity_no')
            component_no = None

            for component in info_data.get('list', []):
                if component.get('comName') == 'turntablecom':
                    component_no = component.get('data', {}).get('component_no')
                    break  # 找到后即可退出循环
            
            if activity_no and component_no:
                logger.info(f"成功获取抽奖活动ID: activity_no={activity_no}, component_no={component_no}")
                return {'activity_no': activity_no, 'component_no': component_no}
            
            logger.error(f"未找到 'turntablecom' 组件或相关ID (activity_no: {activity_no}, component_no: {component_no})")
            return None
        else:
            logger.error(f"获取抽奖活动页面信息失败: {res.get('message', '未知错误')}")
            return None
    except Exception as e:
        logger.error(f"获取抽奖活动信息时发生异常: {e}")
        return None

async def run_basic_tasks(accounts: List[Dict], accounts_map: Dict) -> List[str]:
    """执行所有账户的基础任务（签到、抽奖等）"""
    all_results = []
    for index, user in enumerate(accounts):
        global notify_msg
        notify_msg = []
        
        account_name = user.get('userName', f"账号{index+1}")
        account_id = user.get('account_id', f"账号{index+1}")
        logger.info(f"🚀 开始基础任务 - {account_name} ({account_id})")

        delay = random.randint(5, 15)
        logger.info(f"将在 {delay} 秒后进行下一次签到...")
        await asyncio.sleep(delay)
        await signin(user)
        
        chance, activity_info = await lottery_signin(user)
        logger.info(f"获取抽奖机会成功，共{chance}次")
        
        if chance > 0:
            for _ in range(chance):
                await lottery_clock(user, activity_info)
                await asyncio.sleep(random.uniform(3, 5))
        
        user_info = await get_user_info(user)
        balance_info = await get_balance(user)

        nick_name = user_info.get('nick_name', account_name)
        growth_value = user_info.get('growth_value', 0)
        level = user_info.get('level', 0)
        balance = balance_info.get('balance', 0)
        double_log(f"当前用户: {nick_name}\n成长值: {growth_value}  等级: V{level}  珑珠: {balance}")

        account_result = "\n".join(notify_msg)
        all_results.append(f"===== {account_name} (基础任务) =====\n{account_result}")
    return all_results

async def run_assist_tasks(assist_groups: List[Dict], accounts_map: Dict):
    """处理所有助力任务"""
    logger.info("\n--- 🚀 开始处理助力任务 ---\n")
    for group in assist_groups:
        group_name = group.get("group_name", "未知助力组")
        master_id = group.get("master")
        follower_ids = group.get("followers", [])

        logger.info(f"处理助力组: {group_name} (主账号: {master_id})")

        if not master_id or not follower_ids:
            logger.warning(f"助力组 {group_name} 配置不完整，跳过")
            continue

        master_account = accounts_map.get(master_id)
        if not master_account:
            logger.error(f"在账户列表中未找到主账号 {master_id}，跳过该组")
            continue

        active_tasks = await get_active_assist_task(master_account)
        if not active_tasks:
            logger.info(f"主账号 {master_id} 未找到任何有效的助力活动，跳过该组")
            continue

        for active_task in active_tasks:
            task_title = active_task.get('title', active_task['sub_task_no'])
            logger.info(f"\n--- 正在处理任务: '{task_title}' (主账号: {master_id}) ---\n")

            component_no = active_task['component_no']
            sub_task_no = active_task['sub_task_no']
            task_end_time = active_task.get('end_time')
            task_specific_id = f"{master_id}_{sub_task_no}"

            master_assist_data = None
            if should_launch_assist(task_specific_id, task_end_time):
                logger.info(f"主账号 {master_id} 需要为任务 '{task_title}' 发起新的助力。")
                launch_result = await launch_assist(master_account, sub_task_no, component_no)
                if not launch_result.get('error'):
                    record_assist_launch(task_specific_id, launch_result, task_end_time)
                    master_assist_data = launch_result
                else:
                    logger.error(f"主账号 {master_id} 发起助力任务 '{task_title}' 失败: {launch_result.get('message')}")
                    continue
            else:
                logger.info(f"主账号 {master_id} 的任务 '{task_title}' end_time 未变更，从状态文件加载信息。")
                status = load_assist_status()
                master_assist_data = status.get(task_specific_id)

            if not master_assist_data or not master_assist_data.get('user_task_no'):
                logger.error(f"主账号 {master_id} 的任务 '{task_title}' 缺少有效的助力信息，无法继续。")
                continue

            for follower_id in follower_ids:
                follower_account = accounts_map.get(follower_id)
                if not follower_account:
                    logger.warning(f"在账户列表中未找到从账号 {follower_id}，跳过。")
                    continue
                
                follower_name = follower_account.get('userName', follower_id)
                logger.info(f"  -> 从账号 {follower_name} ({follower_id}) 准备为 {master_id} 的任务 '{task_title}' 助力")

                status = load_assist_status()
                master_task_status = status.get(task_specific_id, {})
                followers_assisted = master_task_status.get('followers_assisted', {})
                
                if follower_id in followers_assisted:
                    last_assist_time_str = followers_assisted[follower_id]
                    try:
                        last_assist_time = datetime.fromisoformat(last_assist_time_str)
                        if is_same_week(last_assist_time, datetime.now()):
                            logger.info(f"  -> 从账号 {follower_id} 本周已为任务 '{task_title}' 助力过，跳过。")
                            continue
                    except ValueError:
                        logger.error(f"解析从账号 {follower_id} 的助力时间失败: {last_assist_time_str}")

                delay_seconds = random.uniform(5, 15)
                logger.info(f"为模拟真人操作，随机等待 {delay_seconds:.2f} 秒后继续...")
                await asyncio.sleep(delay_seconds)

                success = await assist_help(
                    follower_account,
                    user_task_no=master_assist_data['user_task_no'],
                    invite_code=master_assist_data['invite_code']
                )

                if success:
                    record_follower_assist(task_specific_id, follower_id)
                    logger.info(f"  -> ✅ 从账号 {follower_id} 助力 {master_id} 的任务 '{task_title}' 成功")
                else:
                    logger.error(f"  -> ⛔️ 从账号 {follower_id} 助力 {master_id} 的任务 '{task_title}' 失败")
                
                await asyncio.sleep(random.uniform(2, 4))


def send_notification(all_results: List[str]):   
    """汇总所有结果并推送飞书通知"""
    if not all_results:
        logger.info("没有可通知的结果。")
        return

    # ===================== 只需要填这里 =====================
    FEISHU_WEBHOOK = f"https://open.feishu.cn/open-apis/bot/v2/hook/{os.getenv('FSKEY')}"
    # ========================================================

    if not FEISHU_WEBHOOK:
        logger.warning("未配置飞书机器人 WEBHOOK，跳过通知。")
        return

    # 拼接消息内容
    final_content = "\n\n".join(all_results)
    title = "龙湖天街任务通知"
    msg = f"{title}\n\n{final_content}"

    # 飞书消息格式
    payload = {
        "msg_type": "text",
        "content": {
            "text": msg
        }
    }

    try:
        resp = requests.post(
            FEISHU_WEBHOOK,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"}
        )
        logger.info(f"飞书通知已发送：{resp.text}")
    except Exception as e:
        logger.error(f"飞书通知发送失败：{str(e)}")
def send_notificationDD(all_results: List[str]):
    """汇总所有结果并推送钉钉通知"""
    if not all_results:
        logger.info("没有可通知的结果。")
        return
        
    final_content = "\n\n".join(all_results)
    access_token = ''
    webhook = f'https://oapi.dingtalk.com/robot/send?access_token={access_token}'
    secret = ''
    
    if not webhook or not secret:
        logger.warning("未配置钉钉机器人的 WEBHOOK 或 SECRET，跳过通知。")
        return

    xiaoding = DingtalkChatbot(webhook, secret=secret)
    title = "龙湖天街任务通知"
    markdown_text = f"### 龙湖天街任务报告\n\n---\n\n{final_content}"
    xiaoding.send_markdown(title=title, text=markdown_text, is_at_all=False)
    logger.info("钉钉通知已发送。")

async def main(args):
    """主程序"""
    accounts, assist_groups = get_cookies()
    if not accounts:
        logger.error("找不到可用的帐户")
        return

    logger.info(f"发现 {len(accounts)} 个帐户和 {len(assist_groups)} 个助力组")
    accounts_map = {acc['account_id']: acc for acc in accounts}

    all_results = []
    
    if not args.assist_only:
        basic_results = await run_basic_tasks(accounts, accounts_map)
        all_results.extend(basic_results)

    if not args.basic_only:
        await run_assist_tasks(assist_groups, accounts_map)
        # 助力任务的日志直接通过 double_log 打印，不在此处收集
        # 如果需要将助力结果也加入通知，需要修改 run_assist_tasks 让其返回结果

    # 如果执行了基础任务，则发送通知
    if all_results:
        send_notification(all_results)
    

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="龙湖天街自动化任务脚本")
    parser.add_argument(
        '--assist-only',
        action='store_true',
        help='如果提供此参数，则只执行助力任务'
    )
    parser.add_argument(
        '--basic-only',
        action='store_true',
        help='如果提供此参数，则只执行签到、抽奖等基础任务'
    )
    args = parser.parse_args()

    asyncio.run(main(args))
