"""Independent arithmetic/source audit; does not import the simulation engine."""
from collections import Counter, defaultdict
from pathlib import Path
import csv
import hashlib
import itertools
import json
import math

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SOURCE_HASHES = {
    "integration_setup_v1/planned_pilot_20.csv": "58e9c3063220ac26c0ce51fdcdb218d80ae32edd59969daa29659ca33372caed",
    "integration_setup_v1/evidence_cards_20.json": "e56bef7b227b01ea634c0abe5bed1a9ef8c245a8e31fbdc0bbf07f26bdef11c7",
}


def read_json(name):
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def close(actual, expected, tolerance=1e-9):
    assert math.isclose(float(actual), float(expected), rel_tol=1e-11, abs_tol=tolerance), (actual, expected)


def analytic(p, s, n):
    acceptance = p["acceptance_probability"]
    q0, q1 = p["baseline_setup_probability"], s["assisted_setup_probability"]
    ps, pf = s["upgrade_given_setup"], s["upgrade_given_no_setup"]
    control_upgrade = pf + q0 * (ps - pf)
    accepted_upgrade = pf + q1 * (ps - pf)
    help_upgrade = (1 - acceptance) * control_upgrade + acceptance * accepted_upgrade
    help_setup = (1 - acceptance) * q0 + acceptance * q1
    total_cost = n * p["offer_cost_per_assigned_help_customer"]
    total_cost += n * acceptance * p["assistance_cost_per_acceptor"]
    total_cost += p["incremental_fixed_cost_per_help_batch"]
    delta = help_upgrade - control_upgrade
    return {
        "control_setup_probability": q0,
        "help_setup_probability": help_setup,
        "control_upgrade_probability": control_upgrade,
        "help_upgrade_probability": help_upgrade,
        "setup_rate_difference": help_setup - q0,
        "upgrade_rate_difference": delta,
        "expected_extra_cost": total_cost,
        "expected_incremental_profit": n * p["upgrade_net_contribution"] * delta - total_cost,
        "break_even_upgrade_rate_difference": total_cost / n / p["upgrade_net_contribution"],
    }


def paired_pmf(p, s, n):
    """Marginalize setup, keep accept-upgrade dependence, convolve T-C pairs."""
    acceptance = p["acceptance_probability"]
    q0, q1 = p["baseline_setup_probability"], s["assisted_setup_probability"]
    ps, pf = s["upgrade_given_setup"], s["upgrade_given_no_setup"]
    pc = pf + q0 * (ps - pf)
    single_pair = defaultdict(float)
    for accepts, pa in ((0, 1 - acceptance), (1, acceptance)):
        pu = pf + (q1 if accepts else q0) * (ps - pf)
        for upgrade_t, pt in ((0, 1 - pu), (1, pu)):
            for upgrade_c, pb in ((0, 1 - pc), (1, pc)):
                value = p["upgrade_net_contribution"] * (upgrade_t - upgrade_c)
                value -= p["offer_cost_per_assigned_help_customer"]
                value -= p["assistance_cost_per_acceptor"] * accepts
                single_pair[value] += pa * pt * pb
    distribution = {0: 1.0}
    for _ in range(n):
        next_distribution = defaultdict(float)
        for total, weight in distribution.items():
            for value, probability in single_pair.items():
                next_distribution[total + value] += weight * probability
        distribution = next_distribution
    fixed = p["incremental_fixed_cost_per_help_batch"]
    distribution = {value - fixed: prob for value, prob in sorted(distribution.items())}
    close(sum(distribution.values()), 1)
    return distribution


def pmf_summary(distribution):
    mean = sum(value * prob for value, prob in distribution.items())
    variance = sum((value - mean) ** 2 * prob for value, prob in distribution.items())
    positive = sum(prob for value, prob in distribution.items() if value > 0)
    def quantile(q):
        cumulative = 0.0
        for value, probability in sorted(distribution.items()):
            cumulative += probability
            if cumulative >= q:
                return value
        raise AssertionError("CDF did not reach requested quantile")
    return mean, variance, positive, [quantile(.025), quantile(.975)]


def main():
    p, result, lock = read_json("protocol.json"), read_json("results.json"), read_json("execution_lock.json")
    for path, expected_hash in SOURCE_HASHES.items():
        actual_hash = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        assert actual_hash == expected_hash == lock["source_sha256"][path] == result["source_sha256"][path]
    for path, expected_hash in lock["protocol_code_sha256"].items():
        assert hashlib.sha256((HERE / path).read_bytes()).hexdigest() == expected_hash == result["protocol_code_sha256"][path]
    roster = read_csv(ROOT / p["roster"])
    cards = json.loads((ROOT / p["evidence_cards"]).read_text(encoding="utf-8"))
    by_customer = {row["customer_id"]: row for row in cards}
    assert len(roster) == len(cards) == len(by_customer) == len({r["customer_id"] for r in roster}) == 20
    assert len({r["ticket_id"] for r in roster}) == 20
    assert set(by_customer) == {r["customer_id"] for r in roster}
    arm_counts = Counter(r["planned_arm"] for r in roster)
    assert arm_counts == {"OFFER_INTEGRATION_SETUP_HELP": 10, "EXISTING_SUPPORT": 10}
    product_counts = Counter(r["product"] for r in roster)
    assert set(product_counts) == {"Loom", "Trello", "Bitbucket", "Confluence", "Jira"}
    assert set(product_counts.values()) == {4}
    for product in product_counts:
        assert Counter(r["planned_arm"] for r in roster if r["product"] == product) == {
            "OFFER_INTEGRATION_SETUP_HELP": 2, "EXISTING_SUPPORT": 2}
    observed_fields = ["offer_accepted", "setup_success_7d", "paid_upgrade_30d", "actual_upgrade_contribution", "actual_support_cost"]
    for row in roster:
        card = by_customer[row["customer_id"]]
        assert card["ticket_id"] == row["ticket_id"] and card["product"] == row["product"]
        assert row["allocation_status"] == "PREPARED_NOT_EXECUTED"
        assert row["intervention_executed"] == "False" and row["eligibility_reconfirmation_required"] == "True"
        assert all(row[field] == "" for field in observed_fields)
        assert card["need_confirmed"] is False and card["snapshot_plan"] == "Free" and card["ticket_subject"] == "Integration"
        assert not card["setup_outcome_observed"] and not card["upgrade_outcome_observed"]
        assert all(card[field] is None for field in ("configuration_success", "paid_upgrade", "incremental_profit"))
    assert result["real_interventions_executed"] == result["unique_empirical_customers_added"] == 0
    assert all(result[field] is None for field in ("actual_setup_success_rate", "actual_upgrade_rate_difference", "actual_incremental_profit"))
    assert result["original_pilot_outcomes_modified"] is False

    scenarios = {s["id"]: s for s in p["scenarios"]}
    outputs = {s["scenario"]: s for s in result["scenarios"]}
    assert len(scenarios) == len(outputs) == 4 and set(scenarios) == set(outputs)
    raw_pmf = read_csv(HERE / "exact_profit_distributions.csv")
    raw_first = read_csv(HERE / "fixed_first_replay_20.csv")
    raw_summary = {r["scenario"]: r for r in read_csv(HERE / "scenario_summary.csv")}
    assert len(raw_first) == result["simulated_first_replay_rows"] == 80
    assert Counter(r["scenario"] for r in raw_first) == {key: 20 for key in scenarios}
    n, repetitions = 10, p["repetitions"]
    treatment = np.array([r["planned_arm"] == "OFFER_INTEGRATION_SETUP_HELP" for r in roster])
    rng = np.random.default_rng(p["seed"])
    acceptance_draws = rng.random((repetitions, 20))
    setup_draws = rng.random((repetitions, 20))
    upgrade_draws = rng.random((repetitions, 20))
    accepted = np.zeros((repetitions, 20), dtype=bool)
    accepted[:, treatment] = acceptance_draws[:, treatment] < p["acceptance_probability"]
    costs = np.zeros((repetitions, 20), dtype=np.int64)
    costs[:, treatment] = p["offer_cost_per_assigned_help_customer"]
    costs += accepted * p["assistance_cost_per_acceptor"]
    summaries = []
    for key, scenario in scenarios.items():
        out = outputs[key]
        analytic_values = analytic(p, scenario, n)
        for field, value in analytic_values.items():
            close(out["analytic"][field], value)
            close(raw_summary[key][field], value)
        distribution = paired_pmf(p, scenario, n)
        pmf_rows = [r for r in raw_pmf if r["scenario"] == key]
        file_distribution = {int(r["batch_incremental_profit"]): float(r["probability"]) for r in pmf_rows}
        assert len(file_distribution) == len(pmf_rows) == len(distribution)
        assert set(file_distribution) == set(distribution)
        for value, probability in distribution.items():
            close(file_distribution[value], probability, 1e-13)
        mean, variance, positive, interval = pmf_summary(distribution)
        close(mean, analytic_values["expected_incremental_profit"])
        close(mean, out["exact"]["expected_incremental_profit"])
        close(variance, out["exact"]["variance"])
        close(positive, out["exact"]["probability_strictly_positive_profit"])
        close(positive, raw_summary[key]["exact_probability_profit_positive"])
        assert interval == out["exact"]["central_95_batch_profit_range"]
        assert interval == [int(raw_summary[key]["batch_profit_p025"]), int(raw_summary[key]["batch_profit_p975"])]
        setup = setup_draws < p["baseline_setup_probability"]
        setup[accepted] = setup_draws[accepted] < scenario["assisted_setup_probability"]
        upgrade = np.zeros_like(setup)
        upgrade[setup] = upgrade_draws[setup] < scenario["upgrade_given_setup"]
        upgrade[~setup] = upgrade_draws[~setup] < scenario["upgrade_given_no_setup"]
        arm_net = upgrade.astype(np.int64) * p["upgrade_net_contribution"] - costs
        differences = arm_net[:, treatment].sum(1) - arm_net[:, ~treatment].sum(1)
        differences -= p["incremental_fixed_cost_per_help_batch"]
        mc_mean, mc_positive = float(differences.mean()), float((differences > 0).mean())
        mean_se = math.sqrt(variance / repetitions)
        probability_se = math.sqrt(positive * (1 - positive) / repetitions)
        checks = {
            "mean_incremental_profit": mc_mean,
            "probability_strictly_positive_profit": mc_positive,
            "mean_profit_simulation_se": mean_se,
            "probability_simulation_se": probability_se,
            "mean_help_setup_rate": float(setup[:, treatment].mean()),
            "mean_control_setup_rate": float(setup[:, ~treatment].mean()),
            "mean_help_upgrade_rate": float(upgrade[:, treatment].mean()),
            "mean_control_upgrade_rate": float(upgrade[:, ~treatment].mean()),
        }
        for field, value in checks.items():
            close(out["monte_carlo"][field], value)
        assert out["monte_carlo"]["repetitions"] == repetitions
        assert abs(mc_mean - mean) <= p["numerical_tolerance_standard_errors"] * mean_se
        assert abs(mc_positive - positive) <= p["numerical_tolerance_standard_errors"] * probability_se
        first_rows = [r for r in raw_first if r["scenario"] == key]
        for j, (original, replay) in enumerate(zip(roster, first_rows)):
            assert all(replay[f] == original[f] for f in ("customer_id", "ticket_id", "product"))
            assert replay["assigned_arm"] == original["planned_arm"]
            assert replay["repetition"] == "0" and replay["outcome_kind"] == "SIMULATED_NOT_OBSERVED"
            assert replay["eligibility_assumed_not_verified"] == "True" and replay["real_intervention_executed"] == "False"
            assert replay["sim_help_offered"] == str(bool(treatment[j]))
            assert replay["sim_help_accepted"] == (str(bool(accepted[0, j])) if treatment[j] else "")
            assert replay["sim_setup_success_7d"] == str(bool(setup[0, j]))
            assert replay["sim_paid_upgrade_30d"] == str(bool(upgrade[0, j]))
            assert int(replay["sim_variable_help_cost"]) == costs[0, j]
            assert int(replay["sim_upgrade_contribution"]) == int(upgrade[0, j]) * p["upgrade_net_contribution"]
            assert int(replay["sim_net_contribution_before_batch_fixed_cost"]) == arm_net[0, j]
        first_checks = {
            "repetition": 0, "help_accepted_n": int(accepted[0].sum()),
            "help_setup_n": int(setup[0, treatment].sum()), "control_setup_n": int(setup[0, ~treatment].sum()),
            "help_upgrade_n": int(upgrade[0, treatment].sum()), "control_upgrade_n": int(upgrade[0, ~treatment].sum()),
            "incremental_profit": int(differences[0]), "outcome_kind": "SIMULATED_NOT_OBSERVED",
        }
        assert first_checks == out["fixed_first_replay"]
        close(raw_summary[key]["monte_carlo_mean_profit"], mc_mean)
        close(raw_summary[key]["first_replay_profit"], differences[0])
        summaries.append({"scenario": key, "expected_net_contribution_difference": mean,
                          "probability_simulated_arm_difference_positive": positive,
                          "central_95_simulated_batch_range": interval, "variance": variance,
                          "pmf_support_points": len(distribution), "monte_carlo_mean": mc_mean,
                          "mean_deviation_in_simulation_standard_errors": abs(mc_mean - mean) / mean_se,
                          "probability_deviation_in_simulation_standard_errors": abs(mc_positive - positive) / probability_se,
                          "fixed_first_replay_difference": int(differences[0])})

    grid = read_csv(HERE / "cost_sensitivity.csv")
    keys = list(p["cost_grid"])
    expected_grid = {(key,) + tuple(values) for key in scenarios for values in itertools.product(*(p["cost_grid"][k] for k in keys))}
    actual_grid = {(r["scenario"],) + tuple(int(r[k]) for k in keys) for r in grid}
    assert len(grid) == len(actual_grid) == len(expected_grid) == result["cost_grid_rows"] == 144
    assert actual_grid == expected_grid
    for row in grid:
        settings = {key: int(row[key]) for key in keys}
        expected = analytic({**p, **settings}, scenarios[row["scenario"]], n)
        assert row["all_amounts_are_hypothetical"] == "True"
        for field, value in expected.items():
            close(row[field], value)
    report = {
        "checks": "PASS", "audit_kind": "independent_numerical_and_source_verification_not_blinded",
        "main_module_imported": False, "source_sha256": SOURCE_HASHES,
        "planned_unique_customers": 20, "cards_verified": 20, "assignment": dict(arm_counts),
        "first_replay_rows_verified": len(raw_first), "cost_grid_rows_verified": len(grid),
        "monte_carlo_batches_replayed_per_scenario": repetitions,
        "monte_carlo_maximum_allowed_standard_errors": p["numerical_tolerance_standard_errors"],
        "scenarios": summaries, "original_observed_outcomes_still_empty": True,
        "real_interventions_executed": 0, "new_empirical_customers_added": 0,
        "method": "Marginalize setup within accept status; enumerate correlated accept-upgrade and independent control-upgrade states; convolve 10 single T-C pairs; subtract fixed fee once; independently replay NumPy draws.",
        "limits": [
            "Main protocol and source code were visible; this is independent arithmetic, not a blinded replication.",
            "Probabilities and costs are uncalibrated assumptions; arithmetic PASS does not validate their realism.",
            "P(difference>0) describes randomized simulated arm comparisons, not a probability that the true expected business effect is positive.",
            "The central 95% interval is a model batch-outcome range, not a confidence interval for a measured business effect.",
            "Repeated simulations add no empirical customers; all original real outcomes remain unknown.",
            "The fixed first no-setup-improvement replay is positive despite a negative expected effect, illustrating why one favorable replay is not evidence.",
        ],
    }
    (HERE / "independent_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8", newline="\n")
    lines = ["# 模拟试点独立核验", "", "**PASS：来源、20人分配、80条首批路径、完整离散分布、100,000批数值回放及144格成本条件一致。此结论只验证计算与标记，不验证现实升级或利润。**", "",
             "核验脚本不导入主实验。独立方法先在是否接受帮助的条件下消去配置状态，保留接受与升级的相关性；枚举单个协助客户减独立对照客户的收益分布，再卷积10对，最后只扣一次固定费。主实验则先分别卷积两组，因此两条计算路径不同。脚本曾读取主协议与代码，不声称盲法。", "",
             "原名单和证据卡SHA256与执行前记录一致；20名唯一客户、每产品4名、每产品2:2、总体10:10保持。原资格仍未确认、真实干预仍为False，接受帮助、配置成功、升级和金额结果仍为空。", "",
             "| 情景 | 预期净贡献差 | 模拟A-B差额>0概率 | 固定首批差额 |", "|---|---:|---:|---:|"]
    for row in summaries:
        lines.append(f"| {scenarios[row['scenario']]['label']} | {row['expected_net_contribution_difference']:.2f} | {row['probability_simulated_arm_difference_positive']:.4%} | {row['fixed_first_replay_difference']} |")
    lines.extend(["", "所有金额均为未校准的假设成本单位。概率表示‘20人模拟试点中两组净贡献差大于0’；不能解释为真实业务成功概率。全部蒙特卡洛均值和概率均满足预设8个模拟标准误要求；这个标准误仅衡量100,000次数值计算误差。", "",
                  "固定第0批在积极情景为+670、配置无增量情景也为+270，但相应期望为+14和−130。因此首批看起来赚钱不能验证机制。四情景共用随机数只减少比较噪声，重复固定20人不会产生真实效果证据。", "",
                  "保本升级率增量为6.5个百分点：每批期望额外成本130除以10人×每升级200。真实帮助接受、配置任务、升级和成本数据尚未取得，现实盈利仍未知。", ""])
    (HERE / "independent_audit.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(json.dumps({"checks": "PASS", "first_replay_rows_verified": 80, "cost_grid_rows_verified": 144, "scenarios": summaries}, ensure_ascii=False))


if __name__ == "__main__":
    main()
