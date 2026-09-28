"""
Renames player names in best_single_week.json and franchise_leaders.json.

Safety approach: this does NOT do a text/substring find-replace anywhere
in the raw file. It parses the JSON, walks every string value, and only
replaces a value if it is an EXACT, whole-string match for one of the old
names below. This matters because several of these renames are suffix
additions/removals (e.g. "Chris Godwin" -> "Chris Godwin Jr.", "Travis
Etienne Jr." -> "Travis Etienne") where a naive substring replace could
double up a suffix or corrupt an unrelated string that happens to contain
the same text. Exact whole-value matching makes that impossible.

Before writing anything, it also prints a survey of how many times each
old name and each new name currently appear in each file, so any surprise
(an old name that never appears, a new name that's already present
elsewhere) is visible before the swap happens rather than silently masked
by search-and-replace.
"""

import json

RENAMES = {
    "Chris Godwin": "Chris Godwin Jr.",
    "Travis Etienne Jr.": "Travis Etienne",
    "Kyle Pitts Sr.": "Kyle Pitts",
    "Michael Pittman Jr.": "Michael Pittman",
    "Darrell Henderson Jr.": "Darrell Henderson",
    "Mark Ingram II": "Mark Ingram",
    "Brian Robinson Jr.": "Brian Robinson",
    "Marvin Jones Jr.": "Marvin Jones",
    "Oronde Gadsden": "Oronde Gadsden II",
    "Robby Anderson": "Robbie Chosen",
    "Allen Robinson II": "Allen Robinson",
    "Melvin Gordon III": "Melvin Gordon",
    "Ronald Jones II": "Ronald Jones",
    "Todd Gurley II": "Todd Gurley",
    "Will Fuller V": "Will Fuller",
    "Joshua Palmer": "Josh Palmer",
    "Donald Parham Jr.": "Donald Parham",
    "Jeff Wilson Jr.": "Jeff Wilson",
    "Benny Snell Jr.": "Benny Snell",
    "Irv Smith Jr.": "Irv Smith",
    "DJ Chark Jr.": "DJ Chark",
    "Kenneth Gainwell": "Kenny Gainwell",
    "James Cook III": "James Cook",
}

FILES = ["best_single_week.json", "franchise_leaders.json"]


def count_exact_string_values(obj, target, counts_out):
    """Recursively count exact-match occurrences of target among all
    string values in obj (dict/list/str nesting)."""
    if isinstance(obj, dict):
        for v in obj.values():
            count_exact_string_values(v, target, counts_out)
    elif isinstance(obj, list):
        for v in obj:
            count_exact_string_values(v, target, counts_out)
    elif isinstance(obj, str):
        if obj == target:
            counts_out[0] += 1


def replace_exact_string_values(obj, renames):
    """Recursively replace string values that are an exact match for an
    old name with the corresponding new name. Returns the number of
    replacements made."""
    n = 0
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and v in renames:
                obj[k] = renames[v]
                n += 1
            else:
                n += replace_exact_string_values(v, renames)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if isinstance(v, str) and v in renames:
                obj[i] = renames[v]
                n += 1
            else:
                n += replace_exact_string_values(v, renames)
    return n


def survey(filename, data):
    print(f"\n=== Survey: {filename} ===")
    for old, new in RENAMES.items():
        old_count = [0]
        new_count = [0]
        count_exact_string_values(data, old, old_count)
        count_exact_string_values(data, new, new_count)
        note = ""
        if old_count[0] == 0:
            note = "  (old name not found -- nothing to change here)"
        if new_count[0] > 0:
            note += f"  (new name already present {new_count[0]}x before this change)"
        print(f"  {old!r:28s} -> {new!r:28s}  found {old_count[0]}x{note}")


def main():
    all_data = {}
    for fn in FILES:
        with open(fn) as f:
            all_data[fn] = json.load(f)
        survey(fn, all_data[fn])

    print("\n=== Applying replacements ===")
    for fn in FILES:
        n = replace_exact_string_values(all_data[fn], RENAMES)
        print(f"{fn}: {n} replacements made")
        with open(fn, "w") as f:
            json.dump(all_data[fn], f, indent=2)
            f.write("\n")

    print("\n=== Post-change verification ===")
    for fn in FILES:
        with open(fn) as f:
            data = json.load(f)
        for old in RENAMES:
            c = [0]
            count_exact_string_values(data, old, c)
            if c[0] > 0:
                print(f"  WARNING: {fn} still contains {c[0]}x {old!r} after replacement")
    print("Verification complete -- no warnings above means every old name is fully gone.")


if __name__ == "__main__":
    main()
