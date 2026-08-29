from __future__ import annotations

import os
from typing import Any

import requests


NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2026-03-11"


def notion_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {os.environ['NOTION_TOKEN']}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def get_database(database_id: str) -> dict[str, Any]:
    response = requests.get(
        f"{NOTION_API}/databases/{database_id}",
        headers=notion_headers(),
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def get_data_source_id(database_id: str) -> str:
    database = get_database(database_id)
    data_sources = database.get("data_sources", [])

    if not data_sources:
        raise RuntimeError("Data Sourceが見つかりません。")

    return data_sources[0]["id"]


def title_text(prop: dict[str, Any]) -> str:
    return "".join(item.get("plain_text", "") for item in prop.get("title", []))


def rich_text(prop: dict[str, Any]) -> str:
    return "".join(
        item.get("plain_text", "")
        for item in prop.get("rich_text", [])
    )


def property_text(prop: dict[str, Any]) -> str:
    prop_type = prop.get("type")

    if prop_type == "rich_text":
        return rich_text(prop)

    if prop_type == "title":
        return title_text(prop)

    if prop_type == "number":
        value = prop.get("number")
        return "" if value is None else str(value)

    return ""


def get_active_players(data_source_id: str) -> list[dict[str, str]]:
    players: list[dict[str, str]] = []
    cursor = None

    while True:
        payload = {
            "filter": {
                "property": "Checkbox",
                "checkbox": {"equals": True},
            },
            "page_size": 100,
        }

        if cursor:
            payload["start_cursor"] = cursor

        response = requests.post(
            f"{NOTION_API}/data_sources/{data_source_id}/query",
            headers=notion_headers(),
            json=payload,
            timeout=30,
        )

        response.raise_for_status()
        data = response.json()

        for page in data.get("results", []):
            props = page["properties"]

            players.append(
                {
                    "name": title_text(props["HN"]),
                    "player_id": property_text(props["PlayerID"]),
                    "kingdom": property_text(props["Kingdom"]),
                }
            )

        if not data.get("has_more"):
            break

        cursor = data.get("next_cursor")

        if not cursor:
            break

    return players
    


def main() -> None:
    database_id = os.environ["NOTION_DATABASE_ID"]

    data_source_id = get_data_source_id(database_id)
    players = get_active_players(data_source_id)

    print(f"Active players found: {len(players)}")

    for player in players:
        masked_id = (
            f"***{player['player_id'][-4:]}"
            if len(player["player_id"]) >= 4
            else "***"
        )

        print(
            f"- {player['name']} | "
            f"PlayerID: {masked_id} | "
            f"Kingdom: {player['kingdom']}"
        )


if __name__ == "__main__":
    main()
