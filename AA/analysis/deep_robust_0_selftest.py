# -*- coding: utf-8 -*-
"""Check the vectorised engine in deep_robust_common against run_rs and triple_index_results.csv."""
import pandas as pd

import deep_robust_common as C

cal, sg, lv, gc = C.load()
t = C.selftest(cal, sg, lv, gc)
t.to_csv(C.OUT / "robust_selftest.csv", index=False)
pd.set_option("display.width", 220)
print(t.to_string(index=False))
print("max |cagr_fast - cagr_run_rs|:", (t.cagr_fast - t.cagr_run_rs).abs().max())
print("max |cagr_fast - reference|:", (t.cagr_fast - t.cagr_reference_csv).abs().max())
print("max |mdd_fast - reference|:", (t.mdd_fast - t.mdd_reference_csv).abs().max())
