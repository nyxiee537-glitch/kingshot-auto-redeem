from __future__ import annotations
import hashlib,time,requests
from dataclasses import dataclass
from config import *

@dataclass
class ApiResult:
    status:str
    message:str
    raw_status:str=""
    err_code:int|None=None

FATAL_CODE_STATUSES={"code_expired","code_not_found","code_limit_reached"}
TRANSIENT_STATUSES={"server_busy","unknown"}

def _payload(fid,kid,cdk):
    d={"fid":str(fid).strip(),"cdk":str(cdk).strip(),"kid":str(kid).strip(),"time":str(int(time.time()))}
    encoded="&".join(f"{k}={d[k]}" for k in sorted(d))
    return {"sign":hashlib.md5(f"{encoded}{GIFT_API_ENCRYPT_KEY}".encode()).hexdigest(),**d}

def _headers():
    return {"Accept":"application/json, text/plain, */*","Content-Type":"application/x-www-form-urlencoded",
    "Origin":"https://kingshot-giftcode.centurygame.com","Referer":"https://kingshot-giftcode.centurygame.com/",
    "User-Agent":USER_AGENT}

def classify_api_response(d):
    msg=str(d.get("msg","")).strip().strip(".")
    try: err=int(d.get("err_code")) if d.get("err_code") is not None else None
    except (TypeError,ValueError): err=None
    exact={
      ("RECEIVED",40008):("already_redeemed","すでに交換済みです。"),
      ("SAME TYPE EXCHANGE",40011):("success","同種コードとして交換成功。"),
      ("TIME ERROR",40007):("code_expired","ギフトコードの有効期限切れです。"),
      ("CDK NOT FOUND",40014):("code_not_found","ギフトコードが存在しないか無効です。"),
      ("USED",40005):("code_limit_reached","ギフトコードの全体交換上限に達しています。"),
      ("TIMEOUT RETRY",40004):("server_busy","サーバーから再試行を要求されました。"),
      ("TOO FREQUENT",40019):("rate_limited","このアカウントは一時的に交換頻度制限中です。"),
      ("USER INFO ERROR",40020):("character_info_error","Player ID / Kingdom情報がサーバー側で一致しません。"),
      ("STOVE_LV ERROR",40006):("requirements_not_met","交換条件を満たしていません。"),
      ("RECHARGE_MONEY ERROR",40017):("requirements_not_met","交換条件を満たしていません。"),
      ("RECHARGE_MONEY_VIP ERROR",40018):("requirements_not_met","交換条件を満たしていません。"),
    }
    if msg=="SUCCESS": return ApiResult("success","交換成功。",msg,err)
    if (msg,err) in exact:
        s,m=exact[(msg,err)]; return ApiResult(s,m,msg,err)
    if err==40001 and "not exist" in msg.casefold():
        return ApiResult("player_not_found","プレイヤーが見つかりません。",msg,err)
    return ApiResult("unknown",f"未分類API応答: {msg or 'empty'} / {err}",msg,err)

def redeem_once(fid,kid,cdk):
    payload=_payload(fid,kid,cdk)
    for attempt in range(API_MAX_RETRIES):
        try:
            r=requests.post(GIFT_API_URL,data=payload,headers=_headers(),timeout=HTTP_TIMEOUT)
            if r.status_code==200:
                try:return classify_api_response(r.json())
                except ValueError:return ApiResult("unknown","API応答がJSONではありません。")
            if r.status_code in {429,502,503,504}:
                if attempt<API_MAX_RETRIES-1:
                    time.sleep(API_RETRY_DELAY_SECONDS*(attempt+1));continue
                return ApiResult("server_busy",f"HTTP {r.status_code}が続きました。")
            return ApiResult("unknown",f"HTTP {r.status_code}: {r.text[:160]}")
        except (requests.Timeout,requests.ConnectionError) as e:
            if attempt<API_MAX_RETRIES-1:
                time.sleep(API_RETRY_DELAY_SECONDS*(attempt+1));continue
            return ApiResult("server_busy",f"API通信エラー: {e.__class__.__name__}")
        except requests.RequestException as e:
            return ApiResult("unknown",f"API通信エラー: {e}")
    return ApiResult("server_busy","API接続失敗。")
