"""Reference checks over lkml-parsed LookML, a local stand-in for the Looker validator."""

from __future__ import annotations

import re

FIELD_REFERENCE = re.compile(r"\$\{(\w+)\.(\w+)\}")
BARE_REFERENCE = re.compile(r"\$\{(\w+)\}")
PARAMETER_REFERENCE = re.compile(r"\{%\s*parameter\s+(\w+)\.(\w+)\s*%\}|(\w+)\.(\w+)\._parameter_value")


def declared_fields(parsed: dict[str, dict]) -> dict[str, set[str]]:
    """{view name: field names}, including fields inherited through 'extends'."""
    own: dict[str, set[str]] = {}
    parents: dict[str, list[str]] = {}
    for document in parsed.values():
        for view in document.get("views", []):
            names = {item["name"] for key in ("dimensions", "measures", "parameters")
                     for item in view.get(key, [])}
            names |= {f"{item['name']}_{timeframe}" for item in view.get("dimension_groups", [])
                      for timeframe in item.get("timeframes", [])}
            own[view["name"]] = names
            parents[view["name"]] = view.get("extends__all", [[]])[0]

    def resolve(view_name: str) -> set[str]:
        """Own fields plus every ancestor's."""
        names = set(own.get(view_name, set()))
        for parent in parents.get(view_name, []):
            names |= resolve(parent)
        return names

    return {view_name: resolve(view_name) for view_name in own}


def sql_texts(parsed: dict[str, dict]) -> list[tuple[str, str]]:
    """(owning view, sql) for every sql-like property; explore properties belong to the base view."""
    texts: list[tuple[str, str]] = []
    for document in parsed.values():
        for view in document.get("views", []):
            if "derived_table" in view:
                texts.append((view["name"], view["derived_table"]["sql"]))
            for key in ("dimensions", "measures"):
                texts.extend((view["name"], item["sql"]) for item in view.get(key, []) if "sql" in item)
        for explore in document.get("explores", []):
            for key in ("sql_always_where", "sql_always_having"):
                if key in explore:
                    texts.append((explore.get("view_name", explore["name"]), explore[key]))
            texts.extend((explore.get("view_name", explore["name"]), join.get("sql_on", "")) for join in explore.get("joins", []))
    return texts


def unresolved_references(parsed: dict[str, dict]) -> list[str]:
    """Every ${view.field}, ${field}, or parameter reference that names no declared field."""
    fields = declared_fields(parsed)
    unresolved = []
    for document in parsed.values():
        for explore in document.get("explores", []):
            for view_name in [explore.get("view_name", explore["name"])] + [join["name"] for join in explore.get("joins", [])]:
                if view_name not in fields:
                    unresolved.append(f"explore {explore['name']}: view {view_name}")
    for owner, sql in sql_texts(parsed):
        for view_name, field_name in FIELD_REFERENCE.findall(sql):
            known = fields.get(view_name)
            if field_name == "SQL_TABLE_NAME" and known is not None:
                continue
            if field_name not in (known or set()):
                unresolved.append(f"{owner}: ${{{view_name}.{field_name}}}")
        for match in PARAMETER_REFERENCE.finditer(sql):
            view_name, field_name = (match.group(1), match.group(2)) if match.group(1) else match.groups()[2:]
            if field_name not in fields.get(view_name, set()):
                unresolved.append(f"{owner}: parameter {view_name}.{field_name}")
        for field_name in BARE_REFERENCE.findall(sql):
            if field_name != "TABLE" and field_name not in fields.get(owner, set()):
                unresolved.append(f"{owner}: ${{{field_name}}}")
    return unresolved


def foreign_explore_references(parsed: dict[str, dict]) -> list[str]:
    """Explore filters and joins that reference a view which is not part of that explore."""
    problems = []
    for document in parsed.values():
        for explore in document.get("explores", []):
            members = {explore.get("view_name", explore["name"])} | {join["name"] for join in explore.get("joins", [])}
            texts = [explore.get("sql_always_where", ""), explore.get("sql_always_having", "")]
            texts += [join.get("sql_on", "") for join in explore.get("joins", [])]
            for text in texts:
                problems.extend(f"{explore['name']}: {view_name}" for view_name, _ in FIELD_REFERENCE.findall(text)
                                if view_name not in members)
    return problems
