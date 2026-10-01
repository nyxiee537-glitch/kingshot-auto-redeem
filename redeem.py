from __future__ import annotations
import json,os,time
from dataclasses import dataclass
from api_client import FATAL_CODE_STATUSES,redeem_once
from config import *
from test_notion import get_active_players,get_data_source_id

@dataclass
class RedeemResult:
    name:str; status:str; message:str

def redeem_player(p,code,n):
    name=p.get("name","").strip() or f"Player-{n}"
    fid=p.get("player_id","").strip(); kid=p.get("kingdom","").strip()
    if not fid:return RedeemResult(name,"failed","Player IDが空です。")
    if not kid:return RedeemResult(name,"failed","Kingdomが空です。")
    print(f"[{n}] {name} | K{kid} | ***{fid[-4:]}")
    retries=0
    while True:
        r=redeem_once(fid,kid,code)
        if r.status!="server_busy":return RedeemResult(name,r.status,r.message)
        retries+=1
        if retries>API_RATE_LIMIT_MAX_RETRIES:return RedeemResult(name,"server_busy",r.message)
        print(f"  ⏳ {API_RATE_LIMIT_RETRY_SECONDS}秒後に再試行 ({retries}/{API_RATE_LIMIT_MAX_RETRIES})")
        time.sleep(API_RATE_LIMIT_RETRY_SECONDS)

def save_summary(code,results,fatal=""):
    counts={}
    for r in results:counts[r.status]=counts.get(r.status,0)+1
    s={"gift_code":code,"total_players":len(results),"counts":counts,"fatal_code_status":fatal,
       "results":[{"name":r.name,"status":r.status,"message":r.message} for r in results]}
    SUMMARY_JSON_FILE.write_text(json.dumps(s,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    lines=[f"Gift code: {code}",f"Total processed: {len(results)}","","Summary:"]
    lines += [f"- {k}: {v}" for k,v in sorted(counts.items())]
    lines += ["","Players:"]+[f"- {r.name} | {r.status} | {r.message}" for r in results]
    SUMMARY_TEXT_FILE.write_text("\n".join(lines)+"\n",encoding="utf-8")
    return s

def main():
    code=os.environ["GIFT_CODE"].strip()
    ds=get_data_source_id(os.environ["NOTION_DATABASE_ID"])
    players=get_active_players(ds)
    if not players:raise RuntimeError("NotionにActiveのプレイヤーがいません。")
    RESULTS_DIR.mkdir(parents=True,exist_ok=True)
    print(f"Gift code: {code} | Active: {len(players)} | Direct API")
    results=[];fatal=""
    for i,p in enumerate(players,1):
        r=redeem_player(p,code,i);results.append(r)
        if r.status in FATAL_CODE_STATUSES:
            fatal=r.status;print(f"🛑 コード全体エラー: {fatal}");break
        if i<len(players):time.sleep(API_PLAYER_INTERVAL_SECONDS)
    print(json.dumps(save_summary(code,results,fatal),ensure_ascii=False,indent=2))

if __name__=="__main__":main()
