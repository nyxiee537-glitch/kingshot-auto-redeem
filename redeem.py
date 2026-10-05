from __future__ import annotations
import json,os,time
from dataclasses import dataclass
from pathlib import Path
from api_client import FATAL_CODE_STATUSES,redeem_once
from config import *
from test_notion import get_active_players,get_data_source_id

TERMINAL_STATUSES={"success","already_redeemed","failed","requirements_not_met","character_info_error","player_not_found","code_expired","code_not_found","code_limit_reached"}
RETRYABLE_STATUSES={"server_busy","unknown","rate_limited"}

@dataclass
class RedeemResult:
    name:str; status:str; message:str; player_id:str=""

def redeem_player(p,code,n):
    name=p.get("name","").strip() or f"Player-{n}"
    fid=p.get("player_id","").strip(); kid=p.get("kingdom","").strip()
    if not fid:return RedeemResult(name,"failed","Player IDが空です。",fid)
    if not kid:return RedeemResult(name,"failed","Kingdomが空です。",fid)
    print(f"[{n}] {name} | K{kid} | ***{fid[-4:]}")
    r=redeem_once(fid,kid,code)
    return RedeemResult(name,r.status,r.message,fid)

def load_validation():
    fn=os.environ.get("VALIDATION_RESULTS_FILE","").strip()
    if not fn or not Path(fn).exists(): return {}
    try:d=json.loads(Path(fn).read_text(encoding="utf-8"))
    except Exception:return {}
    return {str(v.get("player_id","")).strip():v for v in d.values()
            if isinstance(v,dict) and str(v.get("player_id","")).strip()}

def load_progress():
    if not REDEEM_PROGRESS_FILE.exists(): return {}
    try:
        d=json.loads(REDEEM_PROGRESS_FILE.read_text(encoding="utf-8"))
        return d if isinstance(d,dict) else {}
    except Exception:return {}

def save_progress(data):
    REDEEM_PROGRESS_FILE.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

def result_to_dict(r):
    return {"name":r.name,"status":r.status,"message":r.message,"player_id":r.player_id}

def save_summary(code,results,fatal="",api_outage=False,restricted=False):
    counts={}
    for r in results:counts[r.status]=counts.get(r.status,0)+1
    s={"gift_code":code,"total_players":len(results),"counts":counts,"fatal_code_status":fatal,"api_outage":api_outage,"restricted":restricted,
       "results":[{"name":r.name,"status":r.status,"message":r.message} for r in results]}
    SUMMARY_JSON_FILE.write_text(json.dumps(s,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    lines=[f"Gift code: {code}",f"Total processed: {len(results)}","","Summary:"]
    lines += [f"- {k}: {v}" for k,v in sorted(counts.items())]
    lines += ["","Players:"]+[f"- {r.name} | {r.status} | {r.message}" for r in results]
    SUMMARY_TEXT_FILE.write_text("\n".join(lines)+"\n",encoding="utf-8")
    return s

def main():
    started=time.monotonic()
    code=os.environ["GIFT_CODE"].strip()
    players=get_active_players(get_data_source_id(os.environ["NOTION_DATABASE_ID"]))
    if not players:raise RuntimeError("NotionにActiveのプレイヤーがいません。")
    RESULTS_DIR.mkdir(parents=True,exist_ok=True)
    validation=load_validation(); fatal=""; api_outage=False; consecutive_api_failures=0
    restricted=any(v.get("status")=="requirements_not_met" for v in validation.values())
    progress=load_progress(); code_progress=progress.setdefault(code,{})
    player_by_id={str(p.get("player_id","")).strip():p for p in players if str(p.get("player_id","")).strip()}
    number_by_id={str(p.get("player_id","")).strip():i for i,p in enumerate(players,1)}

    # Remove stale IDs no longer Active; keep progress tied to the current target list.
    for fid in list(code_progress):
        if fid not in player_by_id: code_progress.pop(fid,None)
    save_progress(progress)

    print(f"Gift code: {code} | Active: {len(players)} | Direct API")
    pending=[]
    for i,p in enumerate(players,1):
        fid=str(p.get("player_id","")).strip()
        old=code_progress.get(fid,{}) if fid else {}
        if old.get("status") in TERMINAL_STATUSES:
            print(f"[{i}] {p.get('name','') or old.get('name','')} | saved result reused: {old.get('status')}")
            continue
        pending.append((p,i))

    round_no=0
    while pending and not fatal and not api_outage:
        round_no+=1
        if round_no>1:
            remaining=max(0,int(API_RUN_BUDGET_SECONDS-(time.monotonic()-started)))
            if remaining < API_RETRY_COOLDOWN_SECONDS + API_FINISH_MARGIN_SECONDS:
                print(f"⏱️ 実行時間の安全マージンに到達。{len(pending)}件を次回へ保存します。")
                break
            print(f"⏳ Retry round {round_no}: {API_RETRY_COOLDOWN_SECONDS}s cooldown | pending={len(pending)}")
            time.sleep(API_RETRY_COOLDOWN_SECONDS)

        next_pending=[]
        for pos,(p,i) in enumerate(pending):
            if time.monotonic()-started >= API_RUN_BUDGET_SECONDS:
                next_pending.extend(pending[pos:])
                print(f"⏱️ 実行時間上限に接近。{len(next_pending)}件を次回へ保存します。")
                break
            fid=str(p.get("player_id","")).strip()
            if round_no==1 and fid in validation:
                v=validation[fid]
                r=RedeemResult(p.get("name","").strip() or v.get("name","") or f"Player-{i}",v.get("status","unknown"),v.get("message",""),fid)
                print(f"[{i}] {r.name} | validator result reused: {r.status}")
            else:
                r=redeem_player(p,code,i)

            if r.status in FATAL_CODE_STATUSES:
                code_progress[fid]=result_to_dict(r); save_progress(progress); fatal=r.status; break

            if r.status in {"server_busy","unknown"}:
                consecutive_api_failures+=1
            else:
                consecutive_api_failures=0

            code_progress[fid]=result_to_dict(r); save_progress(progress)
            if r.status in RETRYABLE_STATUSES:
                next_pending.append((p,i))
                print(f"  ↪️ {r.name}: {r.status} → retry queue")

            if consecutive_api_failures>=API_CONSECUTIVE_FAILURE_LIMIT:
                api_outage=True
                print(f"🛑 API unavailable/unreliable for {consecutive_api_failures} consecutive players. Stopping this run.")
                break
            if pos < len(pending)-1: time.sleep(API_PLAYER_INTERVAL_SECONDS)

        pending=next_pending
        if not pending or fatal or api_outage: break

    # Build one complete summary from persisted results for all currently Active players.
    results=[]
    for i,p in enumerate(players,1):
        fid=str(p.get("player_id","")).strip(); d=code_progress.get(fid)
        if d:
            results.append(RedeemResult(d.get("name") or p.get("name","") or f"Player-{i}",d.get("status","unknown"),d.get("message",""),fid))
        else:
            results.append(RedeemResult(p.get("name","") or f"Player-{i}","pending","次回再試行。",fid))

    summary=save_summary(code,results,fatal,api_outage,restricted)
    print(json.dumps(summary,ensure_ascii=False,indent=2))

    complete=(not fatal and not api_outage and all(r.status in TERMINAL_STATUSES for r in results))
    if complete:
        progress.pop(code,None); save_progress(progress)

if __name__=="__main__":main()
