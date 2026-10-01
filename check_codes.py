from __future__ import annotations
import argparse,json,os,subprocess,sys
from datetime import datetime,timedelta,timezone
from pathlib import Path
from api_client import FATAL_CODE_STATUSES,TRANSIENT_STATUSES,redeem_once
from config import *
from notifier import send_detection_notification,send_redeem_notification,send_source_error_notification
from sources import collect_sources
from test_notion import get_active_players,get_data_source_id

PENDING_CODES_FILE=Path("pending_codes.json"); PROCESSING_STALE_MINUTES=30
def now():return datetime.now(timezone.utc)
def load_state():
    if not SEEN_CODES_FILE.exists():return False,set(),{},set()
    try:d=json.loads(SEEN_CODES_FILE.read_text(encoding="utf-8"))
    except Exception:return False,set(),{},set()
    return bool(d.get("initialized")),set(d.get("seen_codes",[])),dict(d.get("processing_codes",{})),set(d.get("announced_codes",[]))
def save_state(seen,processing,announced):
    SEEN_CODES_FILE.write_text(json.dumps({"initialized":True,"seen_codes":sorted(seen,key=str.casefold),
      "announced_codes":sorted(announced,key=str.casefold),
      "processing_codes":{k:processing[k] for k in sorted(processing,key=str.casefold)}},
      ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
def clean_stale(processing):
    cutoff=now()-timedelta(minutes=PROCESSING_STALE_MINUTES)
    for c,v in list(processing.items()):
        try:dt=datetime.fromisoformat(str(v).replace("Z","+00:00"))
        except Exception:dt=None
        if dt is None or dt<=cutoff:processing.pop(c,None)
def save_pending(x):PENDING_CODES_FILE.write_text(json.dumps(x,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
def load_pending():
    if not PENDING_CODES_FILE.exists():return []
    try:d=json.loads(PENDING_CODES_FILE.read_text(encoding="utf-8"))
    except Exception:return []
    return d if isinstance(d,list) else []

def validation_players():
    players = get_active_players(get_data_source_id(os.environ["NOTION_DATABASE_ID"]))
    wanted = {
        "normal": VALIDATION_NORMAL_PLAYER_ID,
        "vip": VALIDATION_VIP_PLAYER_ID,
    }

    missing_secrets = [label for label, player_id in wanted.items() if not player_id]
    if missing_secrets:
        raise RuntimeError(
            "検証用GitHub Secretが未設定です: "
            + ", ".join(missing_secrets)
        )

    by_id = {str(p.get("player_id", "")).strip(): p for p in players}
    selected = {}
    for label, player_id in wanted.items():
        player = by_id.get(player_id)
        if player is None:
            raise RuntimeError(
                f"検証用{label}アカウントがNotionのActive一覧に見つかりません。"
            )
        selected[label] = player

    if wanted["normal"] == wanted["vip"]:
        raise RuntimeError("NormalとVIPの検証Player IDが同じです。")

    return selected


def validate(code, validators):
    results = {}

    # Always test BOTH fixed accounts before deciding.
    for label in ("normal", "vip"):
        p = validators[label]
        r = redeem_once(
            p.get("player_id", "").strip(),
            p.get("kingdom", "").strip(),
            code,
        )
        results[label] = r
        print(
            f"[VALIDATE-{label.upper()}] {code} / "
            f"{p.get('name','?')}: {r.status}"
        )

    statuses = {label: result.status for label, result in results.items()}

    # A definitive global-code error is accepted only if BOTH validators
    # independently return the same fatal status. This avoids rejecting a
    # usable code because of one anomalous account response.
    fatal = [
        r.status for r in results.values()
        if r.status in FATAL_CODE_STATUSES
    ]
    if len(fatal) == 2 and fatal[0] == fatal[1]:
        return "invalid", f"normal={statuses['normal']}, vip={statuses['vip']}"

    recognized = {"success", "already_redeemed", "requirements_not_met"}

    # If either account proves that the code is recognized, it is valid.
    # This covers VIP-only codes:
    # normal=requirements_not_met + vip=success => valid.
    if any(r.status in recognized for r in results.values()):
        return "valid", f"normal={statuses['normal']}, vip={statuses['vip']}"

    # Character/player errors never prove that the gift code is invalid.
    # Conflicting fatal/transient/account results are retried next Cron.
    return "retry", f"normal={statuses['normal']}, vip={statuses['vip']}"


def run_redeemer(code):
    env=os.environ.copy();env["GIFT_CODE"]=code
    for p in (SUMMARY_JSON_FILE,SUMMARY_TEXT_FILE):
        if p.exists():p.unlink()
    subprocess.run([sys.executable,"redeem.py"],env=env,check=False)
    if not SUMMARY_JSON_FILE.exists():return False,{}
    try:s=json.loads(SUMMARY_JSON_FILE.read_text(encoding="utf-8"))
    except Exception:return False,{}
    if s.get("fatal_code_status"):return True,s
    retry={"server_busy","unknown"}
    terminal={"success","already_redeemed","failed","requirements_not_met","character_info_error","player_not_found",
              "code_expired","code_not_found","code_limit_reached"}
    results=s.get("results",[])
    ok=bool(results) and all(x.get("status") in terminal for x in results) and not any(x.get("status") in retry for x in results)
    return ok,s

def claim():
    if PENDING_CODES_FILE.exists():PENDING_CODES_FILE.unlink()
    sources,errors=collect_sources()
    if errors:
        try:send_source_error_notification(errors)
        except Exception as e:print("[WARN]",e)
    if not sources:return 1
    codes=set()
    for x in sources.values():codes.update(x)
    initialized,seen,processing,announced=load_state()
    if not initialized:
        save_state(codes,{},codes);print("[BOOTSTRAP] 初期化のみ。");return 0
    clean_stale(processing)
    new=sorted(codes-(seen|set(processing)),key=str.casefold)
    if not new:save_state(seen,processing,announced);print("No new gift codes.");return 0
    validators=validation_players()
    if not validators:return 1
    pending=[];claimed=now().isoformat()
    for code in new:
        src=[n for n,c in sources.items() if code in c]
        verdict,reason=validate(code,validators)
        if verdict=="invalid":
            seen.add(code);print(f"🗑️ INVALID {code}: {reason}");continue
        if verdict=="retry":
            print(f"⏳ VALIDATION RETRY {code}: {reason}");continue
        processing[code]=claimed;pending.append({"code":code,"sources":src})
    fresh=[x for x in pending if x["code"] not in announced]
    announced.update(x["code"] for x in fresh)
    save_state(seen,processing,announced);save_pending(pending)
    for x in fresh:
        try:send_detection_notification(x["code"],x["sources"])
        except Exception as e:print("[WARN notification]",e)
    return 0

def redeem_pending():
    pending=load_pending()
    if not pending:return 0
    initialized,seen,processing,announced=load_state()
    for item in pending:
        code=str(item.get("code","")).strip()
        if code not in processing:continue
        processed,summary=run_redeemer(code)
        if processed:
            seen.add(code);processing.pop(code,None);save_state(seen,processing,announced)
            if summary.get("fatal_code_status"):
                print(f"🛑 {code}: {summary['fatal_code_status']}");continue
            try:send_redeem_notification(code,item.get("sources",[]),summary,SUMMARY_TEXT_FILE)
            except Exception as e:print("[WARN completion]",e)
        else:
            processing.pop(code,None);save_state(seen,processing,announced)
            print(f"⏳ {code}: 次回再試行")
    return 0

def main():
    p=argparse.ArgumentParser();g=p.add_mutually_exclusive_group(required=True)
    g.add_argument("--claim",action="store_true");g.add_argument("--redeem-pending",action="store_true")
    a=p.parse_args();return claim() if a.claim else redeem_pending()
if __name__=="__main__":raise SystemExit(main())
