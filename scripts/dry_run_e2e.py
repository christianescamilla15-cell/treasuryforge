"""Dry-run end-to-end verification script for TreasuryForge.

Exercises the entire paper lifecycle (data -> decision -> gate -> committee -> staging)
using mock data and a temporary state directory, verifying that all stages flow correctly
without placing real orders.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Sequence

from treasuryforge.broker import BrokerReport, decide
from treasuryforge.consultants import Committee
from treasuryforge.deployment_gate import DeploymentGate
from treasuryforge.journal import Journal


def run_dry_run() -> bool:
    print("=== TREASURYFORGE DRY-RUN END-TO-END VERIFICATION ===")

    # 1. Setup temporary state directory
    tmp_dir = tempfile.mkdtemp()
    print(f"[STAGE 1] Created temporary state directory: {tmp_dir}")

    try:
        # 2. Populate synthetic data for two strategies:
        # - BTC: steady positive return path (should clear gate + committee)
        # - ETH: insufficient history (should fail gate)
        print("[STAGE 2] Generating synthetic strategy track records...")

        btc_dir = os.path.join(tmp_dir, "shadow_btc")
        eth_dir = os.path.join(tmp_dir, "shadow_eth")

        j_btc = Journal(btc_dir)
        j_eth = Journal(eth_dir)

        # BTC: 35 intervals, 40000s step (approx 16 days), steady gains
        for i in range(35):
            r = 0.003 if i % 2 == 0 else 0.001
            j_btc.append_event({
                "kind": "shadow",
                "ts": 100000 + i * 40000,
                "r": r
            })

        # ETH: 5 intervals (should fail gate requiring >=30)
        for i in range(5):
            j_eth.append_event({
                "kind": "shadow",
                "ts": 100000 + i * 40000,
                "r": 0.01
            })

        print("  -> BTC shadow journal populated: 35 steps (~16 days), steady gains")
        print("  -> ETH shadow journal populated: 5 steps, too short")

        # 3. Read back records (mimic the orchestrator load function)
        print("[STAGE 3] Loading track records into broker...")
        recs: dict[str, tuple[Sequence[float], Sequence[int]]] = {}
        for src_dir, name, label in [(btc_dir, "shadow", "funding:BTC"), (eth_dir, "shadow", "funding:ETH")]:
            evs = [e for e in Journal(src_dir).read_ledger() if e.get("kind") == name]
            rs = [float(e["r"]) for e in evs]
            ts = [int(e.get("ts", 0)) for e in evs if e.get("ts")]
            recs[label] = (rs, ts)
            print(f"  -> Loaded {label}: {len(rs)} trades, ts range {min(ts)} to {max(ts)}")

        # 4. Evaluate with broker (Gate + Committee)
        print("[STAGE 4] Running broker decide loop (Gate + Committee)...")
        gate = DeploymentGate()
        committee = Committee()
        report: BrokerReport = decide(recs, gate=gate, committee=committee)

        # 5. Process and verify verdicts
        print("[STAGE 5] Analyzing broker decisions...")
        btc_dec = next(d for d in report.decisions if d.strategy == "funding:BTC")
        eth_dec = next(d for d in report.decisions if d.strategy == "funding:ETH")

        print(f"  -> BTC verdict: {btc_dec.action} ({btc_dec.reason})")
        print(f"  -> ETH verdict: {eth_dec.action} ({eth_dec.reason})")

        # Validate that BTC is deployed and ETH is held
        assert btc_dec.action == "DEPLOY", "BTC should clear both gate and committee and be DEPLOY"
        assert eth_dec.action == "HOLD", "ETH should fail the gate and stay HOLD"
        print("  -> Verification of broker logic: PASS")

        # 6. Stage to orchestrator ledger
        print("[STAGE 6] Staging advancements to orchestrator ledger...")
        orch_dir = os.path.join(tmp_dir, "orchestrator")
        orch_journal = Journal(orch_dir)

        staged_count = 0
        for d in report.decisions:
            if d.action == "DEPLOY":
                orch_journal.append_event({
                    "kind": "stage",
                    "ts": 200000,
                    "strategy": d.strategy,
                    "tier": d.tier_fraction,
                    "dsr": d.verdict.dsr,
                    "status": "PENDING_OK"
                })
                staged_count += 1
                print(f"  -> Staged PENDING_OK for {d.strategy} @ {d.tier_fraction:.0%} tier")

        assert staged_count == 1, "Should have exactly 1 staged strategy (BTC)"

        # Verify orchestrator file was written
        events = orch_journal.read_ledger()
        assert len(events) == 1, "Orchestrator journal should contain exactly 1 event"
        assert events[0]["strategy"] == "funding:BTC"
        assert events[0]["status"] == "PENDING_OK"
        print("  -> Verification of orchestrator staging: PASS")

        print("======================================================")
        print("DRY-RUN SUCCESS: All end-to-end verification stages passed!")
        return True

    except Exception as e:
        print(f"\n[FAIL] Dry-run failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        # Cleanup
        shutil.rmtree(tmp_dir)
        print(f"[CLEANUP] Removed temporary directory: {tmp_dir}")


if __name__ == "__main__":
    import sys
    success = run_dry_run()
    sys.exit(0 if success else 1)
