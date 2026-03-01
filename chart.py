from standard import *
import plotly.graph_objects as go


def chart(logs: pd.DataFrame):

    cols = ["schedule", "hour", "load", "id", "mc", "type", "dispatch"]
    df = logs[cols].copy()

    df = logs.copy()  # schedule,hour,load,id,mc,type,dispatch
    df["t"] = (df["schedule"] - 1) * 24 + df["hour"]

    # 1) Per generator: mc and type (assumed constant per id)
    gen_info = df.groupby("id", as_index=False).agg({"mc": "mean", "type": "first"})

    # 2) Order generators by mc (cheapest first)
    gen_info = gen_info.sort_values("mc")
    # gen_order = gen_info["id"].tolist()

    fig = go.Figure()

    for _, row in gen_info.iterrows():
        gen_id = row["id"]
        gen_type = row["type"]
        g = df[df["id"] == gen_id].sort_values("t")
        fig.add_trace(
            go.Scatter(
                x=g["t"],
                y=g["dispatch"],
                mode="lines",
                stackgroup="one",
                name=f"{gen_type} {gen_id}",  # e.g. "nuclear 25"
                line=dict(width=0.5),
            )
        )

    # Load line
    load = df.drop_duplicates("t")[["t", "load"]].sort_values("t")
    fig.add_trace(
        go.Scatter(
            x=load["t"],
            y=load["load"],
            mode="lines",
            name="Load",
            line=dict(color="black", width=2),
            fill=None,
            stackgroup=None,
        )
    )

    fig.update_layout(
        xaxis_title="Hour",
        yaxis_title="Power (MW)",
    )

    fig.show()
