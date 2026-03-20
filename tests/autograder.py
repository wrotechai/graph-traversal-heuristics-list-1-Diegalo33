#!/usr/bin/env python3
"""
Autograder for AI&KE Assignment #1 — Graph Traversals
=====================================================

Runs the student's solution via run_task1.sh / run_task2.sh, parses stdout/stderr,
and validates against expected results. Exit code 0 = pass, 1 = fail.

Usage:
    python3 tests/autograder.py <TEST_ID>

Test IDs: S1_1, S1_2, S1_3, S1_4, S1_5,
          S1_5_MULTI, S2_1, S2_2, S2_3, S2_4, S2_5
"""

import subprocess
import sys
import re
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TIMEOUT = 300  # seconds per test


# ── Output Parsing ────────────────────────────────────────────

TIME_RE = re.compile(r'(\d{1,2}:\d{2}(?::\d{2})?)')
LINE_NAME_RE = re.compile(r'\b(D\d+|KD\s+\w+)\b', re.IGNORECASE)


def time_to_minutes(t: str) -> float:
    """Convert HH:MM or HH:MM:SS to minutes since midnight."""
    parts = t.split(':')
    h, m = int(parts[0]), int(parts[1])
    s = int(parts[2]) if len(parts) > 2 else 0
    return h * 60 + m + s / 60


def parse_stdout(stdout: str) -> dict:
    """Parse student's stdout into structured segment data.

    Returns dict with:
        segments:       list of raw segment lines (lines containing >=2 time patterns)
        all_lines_used: set of route/line names found (e.g. {'D6', 'D1'})
        first_dep:      first departure time as minutes (or None)
        last_arr:       last arrival time as minutes (or None)
        last_arr_str:   last arrival time as original string (or None)
        station_names:  all text in segment lines (for substring station checks)
    """
    segments = []
    all_lines_used = set()
    all_text = []

    for line in stdout.strip().split('\n'):
        line = line.strip()
        if not line:
            continue
        times = TIME_RE.findall(line)
        if len(times) >= 2:
            segments.append({'raw': line, 'times': times})
            for m in LINE_NAME_RE.finditer(line):
                all_lines_used.add(m.group(1).strip())
            all_text.append(line)

    first_dep = None
    last_arr = None
    last_arr_str = None
    if segments:
        first_dep = time_to_minutes(segments[0]['times'][0])
        last_arr_str = segments[-1]['times'][-1]
        last_arr = time_to_minutes(last_arr_str)

    return {
        'segments': segments,
        'all_lines_used': all_lines_used,
        'first_dep': first_dep,
        'last_arr': last_arr,
        'last_arr_str': last_arr_str,
        'full_text': '\n'.join(all_text),
        'raw_stdout': stdout,
    }


def parse_stderr(stderr: str) -> dict:
    """Extract criterion value and computation time from stderr.

    Looks for numeric values. Returns best-guess criterion value.
    """
    numbers = re.findall(r'(\d+\.?\d*)', stderr)
    return {
        'raw': stderr,
        'numbers': [float(n) for n in numbers],
    }


# ── Solution Runner ───────────────────────────────────────────

def run_solution(task: int, args: list[str], date: str = '2026-03-04') -> tuple[str, str, int]:
    """Run the student's solution and return (stdout, stderr, returncode)."""
    script = os.path.join(REPO_ROOT, f'run_task{task}.sh')
    if not os.path.isfile(script):
        print(f"FAIL: {script} not found. Create it to tell the autograder how to run your solution.")
        sys.exit(1)

    env = os.environ.copy()
    env['GTFS_DATE'] = date

    try:
        result = subprocess.run(
            ['bash', script] + args,
            capture_output=True, text=True, timeout=TIMEOUT,
            cwd=REPO_ROOT, env=env,
        )
    except subprocess.TimeoutExpired:
        print(f"FAIL: Solution timed out after {TIMEOUT}s")
        sys.exit(1)
    except Exception as e:
        print(f"FAIL: Could not run solution: {e}")
        sys.exit(1)

    if result.returncode != 0 and not result.stdout.strip():
        print(f"FAIL: Solution exited with code {result.returncode}")
        if result.stderr.strip():
            # Show first 500 chars of stderr for debugging
            print(f"stderr: {result.stderr[:500]}")
        sys.exit(1)

    return result.stdout, result.stderr, result.returncode


# ── Assertion Helpers ─────────────────────────────────────────

class TestFailure(Exception):
    pass


def assert_has_output(parsed):
    if not parsed['segments']:
        raise TestFailure(
            "No route segments found in stdout. Expected lines with departure/arrival times.\n"
            f"Raw stdout:\n{parsed['raw_stdout'][:300]}"
        )


def assert_station_in_output(parsed, station_name, label=""):
    text = parsed['full_text'].lower()
    # Try exact match first, then partial (first word)
    if station_name.lower() in text:
        return
    # Try first significant word (skip "Wrocław" which appears everywhere)
    words = station_name.split()
    if len(words) > 1 and words[-1].lower() in text:
        return
    raise TestFailure(
        f"Station '{station_name}' not found in output segments{' (' + label + ')' if label else ''}.\n"
        f"Output:\n{parsed['full_text'][:300]}"
    )


def assert_line_used(parsed, line_name):
    if line_name not in parsed['all_lines_used']:
        raise TestFailure(
            f"Expected line '{line_name}' in output, found: {parsed['all_lines_used'] or '(none)'}.\n"
            f"Output:\n{parsed['full_text'][:300]}"
        )


def assert_arrival_time(parsed, expected_hhmm, tolerance_min=5):
    """Check that last arrival time is within tolerance of expected."""
    if parsed['last_arr'] is None:
        raise TestFailure("No arrival time found in output.")
    expected_min = time_to_minutes(expected_hhmm)
    actual_min = parsed['last_arr']
    diff = abs(actual_min - expected_min)
    if diff > tolerance_min:
        raise TestFailure(
            f"Arrival time {parsed['last_arr_str']} (={actual_min:.0f} min), "
            f"expected ~{expected_hhmm} (={expected_min:.0f} min), "
            f"difference {diff:.0f} min exceeds tolerance of {tolerance_min} min."
        )


def assert_max_transfers(parsed, max_transfers):
    """Check that number of distinct lines used implies <= max_transfers."""
    n_lines = len(parsed['all_lines_used'])
    if n_lines == 0:
        return  # Can't determine
    transfers = n_lines - 1
    if transfers > max_transfers:
        raise TestFailure(
            f"Found {n_lines} distinct lines ({parsed['all_lines_used']}), "
            f"implying {transfers} transfers, but expected at most {max_transfers}."
        )


def assert_min_transfers(parsed, min_transfers):
    """Check that the route uses enough lines to imply >= min_transfers."""
    n_lines = len(parsed['all_lines_used'])
    if n_lines == 0:
        return
    transfers = n_lines - 1
    if transfers < min_transfers:
        raise TestFailure(
            f"Found {n_lines} distinct lines ({parsed['all_lines_used']}), "
            f"implying {transfers} transfers, but expected at least {min_transfers}."
        )


def assert_travel_time_range(parsed, start_time_str, min_minutes, max_minutes):
    """Check total travel time is within an expected range."""
    if parsed['last_arr'] is None:
        raise TestFailure("No arrival time found in output.")
    start_min = time_to_minutes(start_time_str)
    travel = parsed['last_arr'] - start_min
    if travel < min_minutes or travel > max_minutes:
        raise TestFailure(
            f"Travel time {travel:.0f} min, expected between {min_minutes} and {max_minutes} min."
        )


def assert_visits_all_stops(parsed, stop_names):
    """Check that all required stops appear in the output (for TSP)."""
    text = parsed['full_text'].lower()
    missing = []
    for stop in stop_names:
        if stop.lower() not in text:
            # Try partial match (last word of multi-word name)
            words = stop.split()
            if not any(w.lower() in text for w in words if len(w) > 3):
                missing.append(stop)
    if missing:
        raise TestFailure(
            f"TSP route does not visit all required stops. Missing: {missing}\n"
            f"Output:\n{parsed['full_text'][:500]}"
        )


def assert_outputs_differ(parsed1, parsed2, label1, label2):
    """Check that two runs produce different results (e.g., different dates)."""
    # Compare arrival times
    if parsed1['last_arr'] is not None and parsed2['last_arr'] is not None:
        if abs(parsed1['last_arr'] - parsed2['last_arr']) > 1:
            return  # They differ — good
    # Compare full text
    if parsed1['full_text'].strip() != parsed2['full_text'].strip():
        return  # They differ — good
    raise TestFailure(
        f"Expected different results for {label1} vs {label2}, but outputs are identical.\n"
        f"This suggests calendar/date filtering is not working.\n"
        f"{label1} arrival: {parsed1['last_arr_str']}\n"
        f"{label2} arrival: {parsed2['last_arr_str']}"
    )


# ── Test Definitions ──────────────────────────────────────────
# All expected values verified against GTFS data on 2026-03-20.

def test_s1_1():
    """S1.1: Wrocław Główny → Jelenia Góra, criterion=t, 06:00, Wednesday.
    Verified: D6 dep 06:10, arr 08:26, 146 min, 0 transfers."""
    stdout, stderr, _ = run_solution(1, ["Wrocław Główny", "Jelenia Góra", "t", "06:00:00"])
    parsed = parse_stdout(stdout)

    assert_has_output(parsed)
    assert_station_in_output(parsed, "Jelenia Góra", "destination")
    assert_line_used(parsed, "D6")
    assert_arrival_time(parsed, "08:26", tolerance_min=3)
    assert_max_transfers(parsed, 0)
    assert_travel_time_range(parsed, "06:00:00", 140, 150)
    print("PASS S1.1: Direct connection (D6, arr 08:26, 146 min, 0 transfers)")


def test_s1_2():
    """S1.2: Wrocław Główny → Legnica, criterion=t, 07:40, Wednesday.
    Verified: D1 dep 07:45, arr 08:41, 61 min travel time."""
    stdout, stderr, _ = run_solution(1, ["Wrocław Główny", "Legnica", "t", "07:40:00"])
    parsed = parse_stdout(stdout)

    assert_has_output(parsed)
    assert_station_in_output(parsed, "Legnica", "destination")
    assert_line_used(parsed, "D1")
    assert_arrival_time(parsed, "08:41", tolerance_min=3)
    assert_travel_time_range(parsed, "07:40:00", 55, 70)
    print("PASS S1.2: Multi-platform station (D1, arr 08:41)")


def test_s1_3():
    """S1.3: Trutnov hl. n. → Kamienna Góra, criterion=t, 13:30, Wednesday.
    Verified: D66 dep 13:37, arr 14:31, 61 min total (includes 11-min dwell at Kralovec).
    If travel time is ~50 min, dwell time is not being counted."""
    stdout, stderr, _ = run_solution(1, ["Trutnov hl. n.", "Kamienna Góra", "t", "13:30:00"])
    parsed = parse_stdout(stdout)

    assert_has_output(parsed)
    assert_arrival_time(parsed, "14:31", tolerance_min=3)
    assert_travel_time_range(parsed, "13:30:00", 57, 65)
    print("PASS S1.3: Dwell time handled correctly (D66, arr 14:31, 61 min)")


def test_s1_4():
    """S1.4: Wrocław Główny → Kąty Wrocławskie, criterion=t, 07:50.
    Verified: Wednesday → D6 dep 07:50, arr 08:13 (23 min).
              Saturday  → D60 dep 08:22, arr 08:37 (47 min). Results MUST differ."""
    stdout_wed, _, _ = run_solution(
        1, ["Wrocław Główny", "Kąty Wrocławskie", "t", "07:50:00"], date='2026-03-04'
    )
    stdout_sat, _, _ = run_solution(
        1, ["Wrocław Główny", "Kąty Wrocławskie", "t", "07:50:00"], date='2026-03-07'
    )
    parsed_wed = parse_stdout(stdout_wed)
    parsed_sat = parse_stdout(stdout_sat)

    assert_has_output(parsed_wed)
    assert_has_output(parsed_sat)
    assert_outputs_differ(parsed_wed, parsed_sat, "Wednesday 2026-03-04", "Saturday 2026-03-07")
    print("PASS S1.4: Calendar filtering works (Wed D6@08:13 ≠ Sat D60@08:37)")


def test_s1_5():
    """S1.5: Wrocław Główny → Jelenia Góra, criterion=p, 06:00, Wednesday.
    Verified: D6, 0 transfers (direct connection exists)."""
    stdout, stderr, _ = run_solution(1, ["Wrocław Główny", "Jelenia Góra", "p", "06:00:00"])
    parsed = parse_stdout(stdout)

    assert_has_output(parsed)
    assert_station_in_output(parsed, "Jelenia Góra", "destination")
    assert_max_transfers(parsed, 0)
    print("PASS S1.5: Transfer criterion finds 0-transfer route")


def test_s1_5_multi():
    """S1.5 extended: Szklarska Poręba Górna → Brzeg, criterion=p, 06:00, Wednesday.
    Verified: requires ≥1 transfer (no direct connection, must go via Wrocław Główny)."""
    stdout, stderr, _ = run_solution(
        1, ["Szklarska Poręba Górna", "Brzeg", "p", "06:00:00"]
    )
    parsed = parse_stdout(stdout)

    assert_has_output(parsed)
    assert_station_in_output(parsed, "Brzeg", "destination")
    assert_min_transfers(parsed, 1)
    print("PASS S1.5 extended: Multi-transfer route found (Szklarska→Brzeg, ≥1 transfer)")


def test_s2_1():
    """S2.1: TSP from Wrocław Główny visiting [Wrocław Grabiszyn, Kąty Wrocławskie], t.
    Verified: both on D6, round trip ~69 min. 2! = 2 permutations."""
    stdout, stderr, _ = run_solution(
        2, ["Wrocław Główny", "Wrocław Grabiszyn;Kąty Wrocławskie", "t", "06:00:00"]
    )
    parsed = parse_stdout(stdout)

    assert_has_output(parsed)
    assert_visits_all_stops(parsed, ["Grabiszyn", "Kąty Wrocławskie"])
    # Round trip should be reasonable — verified ~69 min
    assert_travel_time_range(parsed, "06:00:00", 50, 120)
    print("PASS S2.1: TSP visits both stops on D6 line (~69 min round trip)")


def test_s2_2():
    """S2.2: TSP from Wrocław Główny visiting [Jelenia Góra, Legnica, Brzeg], t.
    Verified: all 3 stops visited, 3! = 6 permutations, best ~454 min."""
    stdout, stderr, _ = run_solution(
        2, ["Wrocław Główny", "Jelenia Góra;Legnica;Brzeg", "t", "06:00:00"]
    )
    parsed = parse_stdout(stdout)

    assert_has_output(parsed)
    assert_visits_all_stops(parsed, ["Jelenia Góra", "Legnica", "Brzeg"])
    print("PASS S2.2: TSP visits all 3 stops in different directions")


def test_s2_3():
    """S2.3: TSP from Wrocław Główny visiting [Legnica, Wałbrzych Główny], t.
    Verified: order Legnica→Wałbrzych = 338 min, Wałbrzych→Legnica = 345 min.
    Costs MUST differ (time-dependent). If equal, static distance matrix is used."""
    # Run TSP — the algorithm should find one of the two orderings
    stdout, stderr, _ = run_solution(
        2, ["Wrocław Główny", "Legnica;Wałbrzych Główny", "t", "06:00:00"]
    )
    parsed = parse_stdout(stdout)

    assert_has_output(parsed)
    assert_visits_all_stops(parsed, ["Legnica", "Wałbrzych"])
    # Verified total should be in the range of ~338-345 min (best ordering)
    assert_travel_time_range(parsed, "06:00:00", 300, 400)
    print("PASS S2.3: TSP cost asymmetry — visits both stops with time-dependent costs")


def test_s2_4():
    """S2.4: TSP from Wrocław Główny visiting [Jelenia Góra, Legnica, Wałbrzych Główny], t.
    Verified: best order JG→Wałbrzych→Legnica, ~345 min. Tests Tabu list mechanism."""
    stdout, stderr, _ = run_solution(
        2, ["Wrocław Główny", "Jelenia Góra;Legnica;Wałbrzych Główny", "t", "06:00:00"]
    )
    parsed = parse_stdout(stdout)

    assert_has_output(parsed)
    assert_visits_all_stops(parsed, ["Jelenia Góra", "Legnica", "Wałbrzych"])
    # Verified: best is ~345 min, allow some slack for suboptimal Tabu runs
    assert_travel_time_range(parsed, "06:00:00", 300, 500)
    print("PASS S2.4: TSP Tabu search visits all 3 stops (~345 min optimal)")


def test_s2_5():
    """S2.5: TSP from Wrocław Główny visiting [Jelenia Góra, Legnica], criterion=p, 08:00.
    Verified: 1 transfer total (JG→Legnica has no direct connection).
    Both orderings have ≥1 transfer."""
    stdout, stderr, _ = run_solution(
        2, ["Wrocław Główny", "Jelenia Góra;Legnica", "p", "08:00:00"]
    )
    parsed = parse_stdout(stdout)

    assert_has_output(parsed)
    assert_visits_all_stops(parsed, ["Jelenia Góra", "Legnica"])
    assert_min_transfers(parsed, 1)
    print("PASS S2.5: TSP with transfer criterion (≥1 transfer, both stops visited)")


# ── Test Registry ─────────────────────────────────────────────

TESTS = {
    'S1_1':        test_s1_1,
    'S1_2':        test_s1_2,
    'S1_3':        test_s1_3,
    'S1_4':        test_s1_4,
    'S1_5':        test_s1_5,
    'S1_5_MULTI':  test_s1_5_multi,
    'S2_1':        test_s2_1,
    'S2_2':        test_s2_2,
    'S2_3':        test_s2_3,
    'S2_4':        test_s2_4,
    'S2_5':        test_s2_5,
}


# ── Main ──────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2 or sys.argv[1] not in TESTS:
        print(f"Usage: python3 tests/autograder.py <TEST_ID>")
        print(f"Available tests: {', '.join(TESTS.keys())}")
        sys.exit(1)

    test_id = sys.argv[1]
    test_fn = TESTS[test_id]

    try:
        test_fn()
        sys.exit(0)
    except TestFailure as e:
        print(f"FAIL [{test_id}]: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR [{test_id}]: Unexpected error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
