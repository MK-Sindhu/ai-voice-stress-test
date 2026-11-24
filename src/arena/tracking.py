"""MLflow logging: one MLflow run per pass of an agent over the scenario set."""

from pathlib import Path

from arena.config import REPO_ROOT


def flatten(d: dict, prefix: str = "") -> dict:
    out = {}
    for key, value in d.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            out.update(flatten(value, name + "."))
        else:
            out[name] = value
    return out


def summary_metrics(summary: dict) -> dict[str, float]:
    """The leaderboard numbers as flat name -> number pairs."""
    return {
        k.replace(".", "_"): float(v)
        for k, v in flatten(summary).items()
        if isinstance(v, int | float) and not isinstance(v, bool)
    }


def log_agent(score: dict, run_dir: Path, params: dict, log=print) -> None:
    """Record each pass: the agent's settings, every metric, and the
    recordings and timelines as artifacts."""
    try:
        import mlflow
    except ImportError:
        log("mlflow is not installed; skipping experiment tracking")
        return
    mlflow.set_tracking_uri(params["mlflow"]["tracking_uri"].replace("sqlite:///", f"sqlite:///{REPO_ROOT}/"))
    mlflow.set_experiment(params["mlflow"]["experiment"])
    manifest = score["run"]
    for rep in score["reps"]:
        with mlflow.start_run(run_name=f"{score['agent']}-rep{rep['rep']}"):
            mlflow.log_params({k: str(v)[:250] for k, v in flatten(manifest["config"]).items()})
            mlflow.set_tags({
                "agent": score["agent"],
                "rep": rep["rep"],
                "git_commit": manifest["git_commit"],
                "scenario_set_version": manifest["scenario_set_version"],
                "clock": manifest["clock"],
                "calibration": str(bool(manifest["config"].get("calibration", False))),
            })
            mlflow.log_metrics(summary_metrics(rep["summary"]))
            mlflow.log_artifacts(str(run_dir / f"rep{rep['rep']}"), artifact_path="calls")
