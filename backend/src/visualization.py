"""Optional matplotlib Gantt visualization."""
def plot_schedule(schedule, path=None):
    import matplotlib.pyplot as plt
    operators=list(dict.fromkeys(schedule.operator)); lanes={k:i for i,k in enumerate(operators)}
    fig,ax=plt.subplots(figsize=(12,max(3,len(operators)*0.45)))
    for row in schedule.itertuples(index=False):
        ax.barh(lanes[row.operator],row.duration,left=row.start,height=0.65)
        ax.text(row.start+row.duration/2,lanes[row.operator],str(row.task_id),ha="center",va="center",fontsize=7)
    ax.set_yticks(range(len(operators)),operators); ax.set_xlabel("Time (minutes)"); ax.set_ylabel("Operator")
    fig.tight_layout()
    if path: fig.savefig(path,dpi=150)
    return fig,ax
