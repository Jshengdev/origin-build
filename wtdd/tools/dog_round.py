"""Run the scripted corridor route on the dog (wtdd/dog/routes/corridor.json) with obstacle avoidance on."""
ARGS = {}


def run():
    from ..commands import do_round
    return {"result": do_round()}
