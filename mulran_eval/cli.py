from __future__ import annotations
import typer
from typing import Optional, List
from rich import print
from pathlib import Path
from .schemas import RunConfig
from .runner import run_once
from .aggregate import aggregate_sweep

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command(help="Run a single evaluation (one sequence)")
def eval(
    seq: str = typer.Argument(..., help="MulRan sequence name, e.g., KAIST01"),
    rate: float = typer.Option(1.0, help="Playback rate"),
    duration_s: int = typer.Option(160, help="Seconds to play when not full-seq"),
    full_seq: bool = typer.Option(False, help="Play full sequence (ignore duration)"),
    out_root: Path = typer.Option(Path("/output"), help="Output root directory"),
    odom_topic: str = typer.Option("/lio_sam/mapping/odometry", help="Odom topic to record"),
    gt_tum_root: Path = typer.Option(Path("/output/gts"), help="Directory of GT TUM files"),
    odom_to_tum: Path = typer.Option(Path("/odom_to_tum.py"), help="Path to odom_to_tum converter"),
    params_file: Optional[Path] = typer.Option(None, help="YAML to inject into SLAM"),
    label: str = typer.Option("base", help="Human-friendly label for this run"),
    sweep_id: Optional[str] = typer.Option(None, help="Group runs under this sweep ID"),
):
    cfg = RunConfig(
        seq=seq,
        rate=rate,
        duration_s=duration_s,
        full_seq=full_seq,
        out_root=str(out_root),
        odom_topic=odom_topic,
        gt_tum_root=str(gt_tum_root),
        odom_to_tum=str(odom_to_tum),
        params_file=str(params_file) if params_file else None,
        label=label,
        sweep_id=sweep_id,
    )
    rec = run_once(cfg)
    print(f"[bold green]Status:[/bold green] {rec.status}  [dim]run_id={rec.run_id}[/dim]\n[dim]{rec.run_dir}[/dim]")


@app.command(help="One-factor-at-a-time sweep with replicates")
def sweep_ofat(
    seq: str = typer.Option(..., help="Sequence name, e.g., KAIST01"),
    sweep_id: str = typer.Option(..., help="Identifier for this sweep"),
    reps: int = typer.Option(10, help="Replicates per setting"),
    rate: float = typer.Option(1.0),
    duration_s: int = typer.Option(300),
    full_seq: bool = typer.Option(False),
    out_root: Path = typer.Option(Path("/output/results_v8")),
    odom_surf: str = typer.Option("0.4,0.5,0.6,0.65,0.7"),
    map_corner: str = typer.Option("0.25,0.3,0.325,0.35,0.375"),
    map_surf: str = typer.Option("0.4,0.5,0.55,0.6,0.65,0.7"),
    params_file: Optional[Path] = typer.Option(None, help="Base YAML; values will be edited in a temp copy"),
):
    from tempfile import NamedTemporaryFile
    from ruamel.yaml import YAML
    yaml = YAML()

    def run_with_params(label: str, overrides: dict):
        # Prepare a temp params file if base provided
        pf = None
        if params_file and params_file.exists():
            data = yaml.load(params_file.read_text(encoding="utf-8")) or {}
            data.update(overrides)
            tmp = NamedTemporaryFile("w", suffix=".yaml", delete=False)
            yaml.dump(data, tmp)
            tmp.flush(); tmp.close()
            pf = Path(tmp.name)
        for r in range(reps):
            cfg = RunConfig(
                seq=seq, rate=rate, duration_s=duration_s, full_seq=full_seq,
                out_root=str(out_root), odom_topic="/lio_sam/mapping/odometry",
                gt_tum_root=str(Path("/output/gts")), odom_to_tum=str(Path("/odom_to_tum.py")),
                params_file=str(pf) if pf else None, label=label, sweep_id=sweep_id,
            )
            run_once(cfg)
        if pf:
            Path(pf).unlink(missing_ok=True)

    # BASELINE
    run_with_params("base", {})

    # OFAT knobs (mirroring your bash arrays)
    for v in [float(x) for x in odom_surf.split(",")]:
        run_with_params(f"Odom surf leaf={v}", {"odometrySurfLeafSize": v})

    for v in [float(x) for x in map_corner.split(",")]:
        run_with_params(f"Map corner leaf={v}", {"mappingCornerLeafSize": v})

    for v in [float(x) for x in map_surf.split(",")]:
        run_with_params(f"Map surf leaf={v}", {"mappingSurfLeafSize": v})

    print("[bold green]Sweep complete. Run 'aggregate' to compute means/stds.[/bold green]")


@app.command(help="Aggregate a sweep into mean/std per config")
def aggregate(
    sweep_id: str = typer.Argument(...),
    out_root: Path = typer.Option(Path("/output"), help="Output root to read/write Parquet logs"),
):
    df = aggregate_sweep(sweep_id, out_root)
    if df.empty:
        print("[yellow]No data found for that sweep_id.[/yellow]")
    else:
        out = out_root.joinpath("logs", f"aggregates_{sweep_id}.parquet")
        print(f"[green]Wrote[/green] {out}  ([dim]{len(df)} rows[/dim])")


def main():
    app()


if __name__ == "__main__":
    main()
