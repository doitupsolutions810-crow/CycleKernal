# CycleKernal Trust Wire

## Problem
simulation_core drew trust from random.uniform(0.6, 0.95). Authority from entropy, not measurement. Research descents 97-98 documented trust boundaries the code didn't enforce.

## Fix
- Trust draws now call evidence_snapshot(failures, runs)
- S = p(1-p), orientation pass/fail/mixed, above_cone flag
- Sample draws: 0/100 S=0.0000 pass; 1/40 S=0.0244 mixed; 3/100 S=0.0291 mixed
- No draw sits above the cone (S > 0.25) - entropy source eliminated

## Success criterion
Every trust value is a measurement with provenance, not a die roll.
