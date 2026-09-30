"""What the help window says about the dataset. Text only, no Qt.

Everything here comes from Vargas' founding works and from the
``dataset.ini`` shipped with the dataset:

- the **2.0.0 data article** (Vargas et al., 2025), which describes the dataset
  as it stands and illustrates five of the ten classes;
- the **1.0.0 data article** (Vargas et al., 2019), which the 2.0.0 one defers
  to for what each event is;
- the **doctoral thesis** behind both (R. E. V. Vargas, 2019, in Portuguese),
  which carries the physics neither article has room for and works through a
  real instance of every event of its time.

None of the three describes every event, and the thesis warns that experts do
not even agree on the names. Where they say nothing, the entry says so: help
text that invents physics is worse than help text that admits a limit. Each
entry names the document it leans on.
"""

from dataclasses import dataclass, field

from overlap_viewer.backend.config import DEFAULT_TRANSIENT_CAPABLE


@dataclass(frozen=True)
class Figure:
    """One illustration of the help: the file to look for and what to say about it."""

    file: str
    width: int
    caption: str
    credit: str


# The example figures of the 2.0.0 article are screenshots of the Petrobras
# labeling tool, whose colors and units are not this viewer's; every caption of
# one says so, since the reader has just been told what the viewer's colors mean.
TOOL_COLORS = (
    "The colors are the labeling tool's, not this viewer's: the lower half of each panel is the "
    "class label (light green normal operation, yellow the transient, red the steady state of "
    "the event) and the upper half the well status, dark green for Open."
)
TOOL_UNITS = (
    "Pressures are in the tool's own units (bar, kPa, kgf/cm²) rather than the pascal of the "
    "dataset."
)


def _paper_figure(number: int) -> str:
    return f"Figure {number} of the 3W Dataset 2.0.0 paper (Vargas et al., 2025), CC BY 4.0"


FIGURES: dict[str, Figure] = {
    "platform-overview": Figure(
        file="platform-v1.jpg",
        width=357,
        caption=(
            "The production path, from the reservoir to the platform. Nearly every event below is "
            "described by where it sits on this path: the production choke (PCK) topside, the "
            "christmas tree and its transducer (TPT) on the seabed, the safety valve (DHSV) in the "
            "tubing, and the downhole gauge (PDG) at the bottom. A pressure rises upstream of "
            "whatever closes or blocks, and falls downstream of it."
        ),
        credit="Figure 1 of the 3W Dataset paper (Vargas et al., 2019)",
    ),
    "platform": Figure(
        file="platform-v2.webp",
        width=880,
        caption=(
            "Where each variable is measured. Left, the subsea christmas tree and its valves, with "
            "the TPT transducer; bottom, the well itself with the safety valve (DHSV) and the "
            "downhole gauge (PDG); right, the topside of the platform, where the production line "
            "reaches the production choke (PCK) and the shutdown valve (SDV), and where the "
            "service pump and the gas compressor feed the service and gas-lift lines. The numbers "
            "are the positions the variable table of the paper refers to."
        ),
        credit=_paper_figure(1),
    ),
    # The five events the 2.0.0 article illustrates, one real instance each, in
    # the variables the paper draws them in. Shown at their own size,
    # so the axis figures stay readable.
    "signature-normal": Figure(
        file="signature-normal.png",
        width=863,
        caption=(
            "A real Normal Operation instance (2015-03-16 10:15 to 2015-03-17 03:00) in which the "
            "well was shut in and its line depressurized, so the class label stays 0 throughout "
            "and the state label tells the story. At 16:00 the production choke (ABER-CKP) closes "
            "from 100 %, the shutdown valve (ESTADO-SDV-P) and the wing valve (ESTADO-W1) both go "
            "to 0, and the tree temperature (T-TPT) collapses from 32 °C to about 5 °C as the flow "
            "stops: Shut-In, grey. The shutdown valve reopens at about 18:10 and the choke partly "
            "with it; the line is depressurized between about 21:00 and 22:00 (salmon); at about "
            "23:00 the wing valve reopens, the temperature recovers at once, and the well is in "
            "Restart (magenta) until the window ends. The lower half of every panel stays light "
            "green: normal operation from end to end, which is what this viewer's state band is "
            "for. " + TOOL_COLORS
        ),
        credit=_paper_figure(7),
    ),
    "signature-dhsv": Figure(
        file="signature-dhsv.png",
        width=865,
        caption=(
            "A real Spurious Closure of DHSV (2017-07-28, 14:00 to 17:30). Until about 15:40 "
            "nothing moves; then the four readings part on either side of the closed valve. Below "
            "it the downhole pressure (P-PDG) climbs by some 30 bar over the rest of the window; "
            "above it the tree pressure (P-TPT), the pressure upstream of the production choke "
            "(P-MON-CKP) and the tree temperature (T-TPT) fall away as the flow stops, the "
            "temperature from 111 °C toward that of the seabed. The experts labeled the transient "
            "from the divergence to about 16:55 and the steady state after it. "
            + TOOL_COLORS
            + " "
            + TOOL_UNITS
        ),
        credit=_paper_figure(3),
    ),
    "signature-severe-slugging": Figure(
        file="signature-severe-slugging.png",
        width=866,
        caption=(
            "A real Severe Slugging instance (2016-08-04, 06:24 to 13:30), labeled in the steady "
            "state from end to end: there is no transient to this event. Every reading cycles "
            "with the same period of about 35 minutes, twelve slugs in seven hours. The downhole "
            "pressure (P-PDG) and the tree pressure (P-TPT) swing by some 12 bar each, the pressure "
            "upstream of the choke (P-MON-CKP) by 2 to 3 bar with a sharp spike as each slug "
            "arrives, and the temperature downstream of the choke (T-JUS-CKP) by about 4 °C in a "
            "sawtooth. " + TOOL_COLORS + " " + TOOL_UNITS
        ),
        credit=_paper_figure(6),
    ),
    "signature-quick-restriction": Figure(
        file="signature-quick-restriction.png",
        width=864,
        caption=(
            "A real Quick Restriction in PCK (2015-06-10, 03:30 to 16:15). The choke opening "
            "(ABER-CKP) holds 100 % until about 11:50, then steps down to some 10 % within an "
            "hour, and every pressure behind the choke rises in answer: upstream of it (P-MON-CKP) "
            "from 9 to about 60 bar, at the tree (P-TPT) from 49 to about 110 bar, downhole (P-PDG) "
            "from 87 to about 170 bar. The pressures keep rising for four hours, and the experts "
            "kept the label in the transient for as long, calling the steady state only in the "
            "last minutes of the window. " + TOOL_COLORS + " " + TOOL_UNITS
        ),
        credit=_paper_figure(4),
    ),
    "signature-hydrate-production": Figure(
        file="signature-hydrate-production.png",
        width=866,
        caption=(
            "A real Hydrate in Production Line (2019-05-03 20:15 to 2019-05-06 08:00, two and a "
            "half days). Upstream of the forming plug the pressures drift up (downhole (P-PDG) "
            "from 167 to about 197 kgf/cm², at the tree (P-TPT) from 12.2 to about 15 MPa) while "
            "downstream of it the pressure upstream of the choke (P-MON-CKP) sags from 5.3 to "
            "about 2.5 MPa and the tree temperature (T-TPT) cools from 25.5 to about 21.5 °C. "
            "Nothing steps: the labels leave normal operation early on 4 May and stay in the "
            "transient for two days, the steady state being called only in the last hour. "
            + TOOL_COLORS
            + " "
            + TOOL_UNITS
        ),
        credit=_paper_figure(5),
    ),
}


@dataclass(frozen=True)
class FaultHelp:
    """What one class label means, and how the literature says it shows in the data.

    ``source`` names the documents each entry leans on, since the three differ
    in what they cover; ``illustration`` names the entry of ``FIGURES`` that
    shows the event, for the five the 2.0.0 article illustrates.
    """

    name: str
    what: str
    signature: str
    figure: str = ""  # the example figure of the 2.0.0 article, when it has one
    illustration: str = ""  # the ``FIGURES`` entry reproducing that figure
    notes: str = ""
    source: str = ""


# The transient code of an event is its class plus the transient offset; the
# events missing from this set have no transient period in the dataset at all.
TRANSIENT_CAPABLE = set(DEFAULT_TRANSIENT_CAPABLE)

# How long a window the well-monitoring analysts at Petrobras look at before
# they will confirm an occurrence (table 1 of both articles and of the thesis).
# It is the time the evidence takes to become conclusive to a human, not how
# long the event lasts, but it is the best published measure of the pace of
# each event, and it says why some of them need a whole instance on screen and
# others a few minutes. Hydrate in Service Line arrived with version 2.0.0 and
# has no published figure.
CONFIRMATION_WINDOWS: dict[int, str] = {
    1: "12 hours",
    2: "5 to 20 minutes",
    3: "5 hours",
    4: "15 minutes",
    5: "12 hours",
    6: "15 minutes",
    7: "72 hours",
    8: "30 minutes to 5 hours",
}

FAULTS: dict[int, FaultHelp] = {
    0: FaultHelp(
        name="Normal Operation",
        what=(
            "The well is in full production, in a steady regime with no significant anomaly. Every "
            "event in the dataset starts from this state. The thesis names four mutually exclusive "
            "states a naturally flowing well can be in, i.e., closed, normal operation, starting and "
            "closing, and warns that no standard or authority defines them, so the vocabulary is "
            "Petrobras's own; version 2.0.0 of the dataset replaced them with the nine operational "
            "statuses this viewer draws in the state band."
        ),
        signature=(
            "Figure 7 of the 2.0.0 article shows a normal instance in which the well was shut down "
            "and the line depressurized: the production choke opening (ABER-CKP) steps down from "
            "100 %, the production wing valve (ESTADO-W1) goes from open to closed, and the tree "
            "temperature (T-TPT) collapses as flow stops, recovering when the valves reopen at "
            "Restart. The normal instances worked through in the 1.0.0 article and in the thesis "
            "carry a warning of their own: in both, one of the three plotted sensors is frozen "
            "from end to end."
        ),
        figure="figure 7",
        illustration="signature-normal",
        notes=(
            "The most numerous class of the dataset, and the only one with no simulated and no "
            "hand-drawn instances: normal operation was never synthesized."
        ),
        source="2.0.0 article, figure 7; thesis, section 1.1.3 and figure 12",
    ),
    1: FaultHelp(
        name="Abrupt Increase of BSW",
        what=(
            "BSW is the ratio of produced water and sediment to produced liquid. It is expected to "
            "climb over a well's life as water arrives from the aquifer or from injection, and the "
            "piping is designed for that; what hurts is a sudden jump, which costs oil production "
            "and brings problems of flow assurance, lifting, scaling and processing at the plant. "
            "No sensor measures BSW, so it has to be read off the pressures and temperatures."
        ),
        signature=(
            "The thesis gives the rule and warns there is no single canonical shape: pressures and "
            "temperatures may move either way, but as a rule <b>the pressures measured deep rise, "
            "the pressures near the surface fall, and the temperatures rise everywhere</b>. In its "
            "worked instance the tree pressure and the pressure upstream of the choke drift down "
            "over hours while the tree temperature and the temperature downstream of the choke "
            "drift up, and the downhole gauge is frozen throughout."
        ),
        notes=(
            "One of the two rarest events in the field: the dataset has very few real instances, "
            "and it is one of only two classes with hand-drawn instances, which the papers reserve "
            "for events that are both rare and hard to simulate. In the thesis's example the well "
            "took about eight and a half hours to reach the steady state."
        ),
        source="thesis, section 2.3.1 and figure 3; 1.0.0 article",
    ),
    2: FaultHelp(
        name="Spurious Closure of DHSV",
        what=(
            "The downhole safety valve sits in the production tubing and is held open by a "
            "hydraulic actuator; it is built to fail closed, so that the well shuts itself in if "
            "the platform is lost. Occasionally it closes on its own, and both the article and the "
            "thesis stress that this usually happens <b>with no indication at the surface at "
            "all</b>, not even a pressure drop in the actuator, which leaves the process "
            "variables as the only evidence. Caught in time it can be reopened by a corrective "
            "procedure, which is exactly what makes predicting it worthwhile."
        ),
        signature=(
            "The closed valve splits the well in two and the readings diverge accordingly: below "
            "it the downhole pressure (P-PDG) builds up, while above it the tree pressure (P-TPT), "
            "the pressure upstream of the production choke (P-MON-CKP) and the tree temperature "
            "(T-TPT) all collapse as the flow stops and the tree cools toward the seabed. In the "
            "thesis's example production had stopped entirely about 35 minutes after the onset."
        ),
        figure="figure 3",
        illustration="signature-dhsv",
        source="2.0.0 article, figure 3; thesis, section 2.3.2 and figure 4",
    ),
    3: FaultHelp(
        name="Severe Slugging",
        what=(
            "The critical flow instability: liquid accumulates and is then expelled in surges, "
            "which cycles the pressure of the whole production path and can stress or damage "
            "equipment in the well and in the plant. Two marks define it: a well-defined "
            "periodicity, around 30, 45 or 60 minutes, and an intensity usually large enough to be "
            "seen by every sensor along the production circuit. Recognized early, the well's "
            "operation can be changed to reverse it."
        ),
        signature=(
            "Regular cycles on everything: oscillations above 10 bar at the downhole gauge "
            "(P-PDG) and the tree (P-TPT), with the pressure upstream of the production choke "
            "(P-MON-CKP) and the temperature downstream of it (T-JUS-CKP) swinging in phase. The "
            "shape is a sawtooth, a slow build and a fast blowdown, and the choke pressure can "
            "show a sharp spike once per cycle as each slug arrives. The thesis's example cycles "
            "about every 67 minutes."
        ),
        figure="figure 6",
        illustration="signature-severe-slugging",
        notes=(
            "Has no transient period: an instance is already in the established oscillating regime "
            "where it is labeled at all."
        ),
        source="2.0.0 article, figure 6; thesis, section 2.3.3 and figure 5",
    ),
    4: FaultHelp(
        name="Flow Instability",
        what=(
            "The milder sibling of severe slugging: at least part of the monitored series shows "
            "relevant but tolerable changes, and what tells the two apart is that these changes "
            "have <b>no periodicity</b>. Neither article nor the thesis offers any mechanism "
            "beyond that contrast. It is worth catching because an instability can grow into "
            "severe slugging, with everything that entails."
        ),
        signature=(
            "The same variables as severe slugging, without the rhythm: the tree pressure and "
            "temperature and the readings around the choke wander aperiodically, by a fraction of "
            "their own level, over minutes to hours. Periodic and intense is severe slugging; "
            "aperiodic and tolerable is flow instability. This contrast is the only discriminator "
            "the sources state."
        ),
        notes=(
            "Has no transient period, and its instances often carry no normal period either. It is "
            "the second most numerous class of the dataset and the only undesirable event with no "
            "simulated instances at all: every one of them is real."
        ),
        source="thesis, section 2.3.4 and figure 6; 1.0.0 article",
    ),
    5: FaultHelp(
        name="Rapid Productivity Loss",
        what=(
            "The productivity of a naturally flowing well rests on reservoir properties (static "
            "pressure, water and sediment content, productivity index, gas-oil ratio, viscosity, etc.) "
            "and the reservoir keeps changing as it empties. When those properties change so far "
            "that the system's energy no longer overcomes its losses, the fluid can no longer "
            "reach the surface and production ceases: in the limit, the well loses its natural "
            "flow. Caught in time, the operators can move the well's operating point instead."
        ),
        signature=(
            "A slow, monotone decline across the board: in the thesis's worked instance the tree "
            "pressure and temperature, the pressure upstream of the choke and the temperature "
            "downstream of it all sag together over about ten hours, the last two so noisy that "
            "the trend reads only as an envelope."
        ),
        notes=(
            "Rare in the field: almost all of its instances in the dataset are simulated. In the "
            "thesis's example the well was intervened after about eight and three quarter hours "
            "and never reached the steady state at all, which is why so many instances of this "
            "class stop in the transient."
        ),
        source="thesis, section 2.3.5 and figure 7; 1.0.0 article",
    ),
    6: FaultHelp(
        name="Quick Restriction in PCK",
        what=(
            "The production choke is the valve at the start of the production unit that controls "
            "the well at the surface, and it is generally operated by hand, so an operational slip "
            "can restrict it sharply. The term is internal to Petrobras and undefined in the "
            "literature; the working definition is a restriction of more than some reference "
            "amplitude, say 5 %, within a short time, say 10 seconds. Being a manual valve, an "
            "unwanted restriction can also be undone quickly."
        ),
        signature=(
            "The choke opening (ABER-CKP) steps down and every pressure behind it rises together "
            "(upstream of the choke (P-MON-CKP), at the tree (P-TPT) and downhole (P-PDG)) while "
            "the tree temperature and the temperature downstream of the choke fall. It develops in "
            "minutes: about eleven, in the thesis's example."
        ),
        figure="figure 4",
        illustration="signature-quick-restriction",
        notes=(
            "Among the rarest events in the field: the dataset holds only a handful of real "
            "instances."
        ),
        source="2.0.0 article, figure 4; thesis, section 2.3.6 and figure 8",
    ),
    7: FaultHelp(
        name="Scaling in PCK",
        what=(
            "Inorganic deposits build up in the production choke and can cut oil and gas "
            "production drastically. Caught in time, a scale inhibitor can be injected before the "
            "production is lost. Neither article nor the thesis says more than that about the "
            "chemistry."
        ),
        signature=(
            "The 2.0.0 article publishes no example, but the thesis's worked instance gives "
            "<b>the same directions as a quick restriction of the same valve</b> (the tree "
            "pressure and the pressure upstream of the choke climb while the tree temperature and "
            "the temperature downstream of the choke fall) spread over some ten hours instead of "
            "ten minutes. Timescale is what tells the two apart: analysts confirm "
            "a restriction within a quarter of an hour and scaling over three days."
        ),
        notes=(
            "The only event that stays rare even after the simulated and hand-drawn instances are "
            "counted, and the one the OLGA simulations could not produce at all, hence its "
            "hand-drawn instances."
        ),
        source="thesis, section 2.3.7 and figure 9; 1.0.0 article",
    ),
    8: FaultHelp(
        name="Hydrate in Production Line",
        what=(
            "A hydrate is a crystalline compound of water and natural gas that looks like ice. It "
            "needs water and gas together at high pressure and low temperature, so lines carrying "
            "dead oil never see it and gas wells see it most, but an oil well can be blocked "
            "outright. Clearing a plug costs days or weeks of production, and sometimes an "
            "offshore rig at more than half a million dollars a day, which is why the shut-in "
            "procedures in the state band exist: depressurizing, flushing the line with diesel or "
            "gas, bullheading."
        ),
        signature=(
            "Pressures rise upstream of the forming plug (downhole (P-PDG) and at the tree "
            "(P-TPT)) while the pressure downstream of it, upstream of the production choke "
            "(P-MON-CKP), falls and the tree temperature (T-TPT) drifts down. It is a slow drift "
            "over hours or days rather than a step. In the thesis's example the collapse of the "
            "tree temperature is what says the flow had stopped completely."
        ),
        figure="figure 5",
        illustration="signature-hydrate-production",
        notes=(
            "The 2.0.0 example spends most of its length in the transient and reaches the steady "
            "state only at the very end, which is why so many instances of the hydrate classes "
            "never reach it at all. In the simulated instances the hydrate was modeled as a valve "
            "closing linearly, a deliberate simplification."
        ),
        source="2.0.0 article, figure 5; thesis, section 2.3.8 and figure 10",
    ),
    9: FaultHelp(
        name="Hydrate in Service Line",
        what=(
            "The same crystalline blockage as in the production line, but in the service line, "
            "the line that carries diesel or gas down to the well for flushing and other "
            "operations against hydrates. The 2.0.0 article says its signature patterns are "
            "distinct from the production line's, without saying what they are."
        ),
        signature=(
            "None of the three documents publishes an example: this event was added with version "
            "2.0.0, and neither the 1.0.0 article nor the thesis covers it. Its own instruments "
            "are the ones on the service line: the pressure downstream of the service pump "
            "(P-JUS-BS) and the service pump flow rate (QBS)."
        ),
        notes="The event type added in version 2.0.0 of the dataset; version 1.0.0 has none of it.",
        source="2.0.0 article",
    ),
}


@dataclass(frozen=True)
class VariableHelp:
    """Where one variable is measured, and what is worth knowing about it.

    ``position`` is the number that marks the sensor in figure 1 of the 2.0.0
    article (the ``platform`` figure above the table), from its table 2. The
    figure before the point names a spot in the production system: 2 is the
    production choke, 14 the downhole gauge, 15 the tree transducer. The
    figure after it tells the measurements taken at that spot apart.
    """

    where: str
    note: str = ""
    position: str = ""
    signature_of: tuple[int, ...] = field(default_factory=tuple)


# Position in the production system, from table 2 and figure 1 of the 2.0.0
# article and section 2.1 of the thesis.
DOWNHOLE = "Downhole, in the production tubing"
TREE = "Subsea christmas tree, on the seabed"
TOPSIDE = "Topside, on the production platform"
GAS_LIFT = "Topside, gas-lift line"
SERVICE = "Topside, service line"

VARIABLES: dict[str, VariableHelp] = {
    "ABER-CKGL": VariableHelp(
        GAS_LIFT, "How far the gas-lift choke is open, in percent.", position="1.1"
    ),
    "ABER-CKP": VariableHelp(
        TOPSIDE,
        "How far the production choke is open, in percent. It sets how much the well may flow, so "
        "it is the variable to read first when the pressures behind it move.",
        position="2.1",
    ),
    "ESTADO-DHSV": VariableHelp(
        DOWNHOLE,
        "State of the downhole safety valve, the valve whose spurious closure is fault class 2. "
        "That closure usually leaves no trace at the surface, which is what makes the event hard.",
        position="3.1",
    ),
    "ESTADO-M1": VariableHelp(TREE, "State of the production master valve.", position="4.1"),
    "ESTADO-M2": VariableHelp(TREE, "State of the annulus master valve.", position="5.1"),
    "ESTADO-PXO": VariableHelp(
        TREE,
        "State of the pig-crossover valve, opened to circulate between the two lines.",
        position="6.1",
    ),
    "ESTADO-SDV-GL": VariableHelp(
        GAS_LIFT, "State of the gas-lift shutdown valve.", position="7.1"
    ),
    "ESTADO-SDV-P": VariableHelp(
        TOPSIDE, "State of the production shutdown valve.", position="8.1"
    ),
    "ESTADO-W1": VariableHelp(TREE, "State of the production wing valve.", position="9.1"),
    "ESTADO-W2": VariableHelp(TREE, "State of the annulus wing valve.", position="10.1"),
    "ESTADO-XO": VariableHelp(TREE, "State of the crossover valve.", position="11.1"),
    "P-ANULAR": VariableHelp(
        TREE,
        "Pressure in the annulus, the space around the production tubing.",
        position="12.1",
    ),
    "P-JUS-BS": VariableHelp(
        SERVICE,
        "Pressure downstream of the service pump. With the pump's flow rate, it is the only "
        "instrumentation on the line where fault class 9 forms.",
        position="13.1",
    ),
    "P-JUS-CKGL": VariableHelp(
        GAS_LIFT, "Pressure downstream of the gas-lift choke.", position="1.2"
    ),
    "P-JUS-CKP": VariableHelp(
        TOPSIDE, "Pressure downstream of the production choke.", position="2.2"
    ),
    "P-MON-CKGL": VariableHelp(
        GAS_LIFT, "Pressure upstream of the gas-lift choke.", position="1.3"
    ),
    "P-MON-CKP": VariableHelp(
        TOPSIDE,
        "Pressure upstream of the production choke, on the platform, at the end of the production "
        "path: downstream of the reservoir, the tubing, the tree and the production line, and "
        "upstream of nothing but the choke itself. So a blockage anywhere along that path (a "
        "closed DHSV, a hydrate plug) starves it and it falls, while a restriction of the choke "
        "backs the flow up against it and it rises. The thesis counts it as reliable when it is "
        "there.",
        position="2.3",
    ),
    "P-MON-SDV-P": VariableHelp(
        TOPSIDE, "Pressure upstream of the production shutdown valve.", position="8.2"
    ),
    "P-PDG": VariableHelp(
        DOWNHOLE,
        "Pressure at the permanent downhole gauge, the deepest measurement there is, next to the "
        "reservoir. It rises whenever something downstream of it closes or blocks. With the tree "
        "pressure it is the most relevant reading for flow analysis and, the thesis notes, also "
        "the one that most often fails or is missing, since the gauge is screwed to the production "
        "tubing and replacing it means pulling the tubing.",
        position="14.1",
    ),
    "PT-P": VariableHelp(
        TREE, "Tree pressure downstream of the production wing valve.", position="4.2"
    ),
    "P-TPT": VariableHelp(
        TREE,
        "Pressure at the tree transducer, between the well and the flowline, inside the christmas "
        "tree and considered reliable. It takes part in the signature of every event illustrated.",
        position="15.1",
    ),
    "QBS": VariableHelp(SERVICE, "Flow rate at the service pump.", position="13.2"),
    "QGL": VariableHelp(
        GAS_LIFT,
        "Gas-lift flow rate: the gas injected to lighten the produced column when the reservoir "
        "can no longer lift it on its own.",
        position="13.3",
    ),
    "T-JUS-CKP": VariableHelp(
        TOPSIDE,
        "Temperature downstream of the production choke, which swings with each slug. The fluid "
        "here can come from several wells at once, but the reading is kept because there is "
        "usually no temperature sensor upstream of the choke.",
        position="2.4",
    ),
    "T-MON-CKP": VariableHelp(
        TOPSIDE, "Temperature upstream of the production choke.", position="2.5"
    ),
    "T-PDG": VariableHelp(
        DOWNHOLE, "Temperature at the permanent downhole gauge.", position="14.2"
    ),
    "T-TPT": VariableHelp(
        TREE,
        "Temperature at the tree transducer, also considered reliable. Flowing fluid keeps the "
        "tree warm, so this reading collapses whenever production stops and is the quickest "
        "confirmation that it did.",
        position="15.2",
    ),
}

# Wording of the well operational status codes, from table 5 of the 2.0.0
# article. The thesis, which predates them, knows only four states and warns
# that no standard defines any of this vocabulary.
STATES: dict[int, str] = {
    0: (
        "All production valves are open and the auxiliary valves closed: the well is producing "
        "under regular conditions. Every other status belongs to a shut-in procedure."
    ),
    1: "At least one valve of the production path is closed, so the well is not producing.",
    2: (
        "Diesel is circulated from the service line into the production line, displacing the "
        "produced fluids toward the platform so that nothing hydrate-prone is left in the line."
    ),
    3: (
        "Gas is circulated from the service line into the production line, removing the liquids "
        "that could form hydrates and leaving a drier line behind."
    ),
    4: (
        "Diesel or gas is injected from the platform into the production line under pressure, "
        "pushing the produced fluids back down into the well."
    ),
    5: (
        "The well is closed and most of the production line is filled with diesel, following a "
        "diesel flush or a bullheading. Hydrates are highly unlikely in this condition."
    ),
    6: (
        "The well is closed and most of the production line is filled with natural gas, following "
        "a gas flush. This also mitigates the risk of hydrates."
    ),
    7: (
        "The production valves have just been reopened after a shut-in: a transient period before "
        "the well settles back into regular production."
    ),
    8: (
        "After a shut-in, the production shutdown valve and the choke are opened while the tree "
        "valves stay closed, so the line loses pressure and moves away from the conditions in "
        "which hydrates form."
    ),
}

# The dataset's own facts, for the tab that explains what is being looked at.
DATASET_NOTES = [
    (
        "One file, one instance",
        (
            "The dataset stores one parquet file per instance, sampled/interpolated once a second, in a folder "
            "named after the class of the event it carries. A real instance is named after its "
            "well and the timestamp of its first sample, which is the name this viewer writes "
            "inside each bar."
        ),
    ),
    (
        "Why instances overlap",
        (
            "The real instances of one well are windows cut from the same continuous recording, "
            "and nothing keeps two of them apart in time. Where they overlap, the same samples "
            "enter a dataset twice, and often under different labels, since the end of one "
            "instance can be the normal period that precedes the event another one records. None "
            "of the three documents says how the windows were cut, or whether they may overlap; "
            "showing that they do is what this viewer is for. Thankfully, label conflicts are trivial."
        ),
    ),
    (
        "Real, simulated and hand-drawn",
        (
            "Instances come from field recordings, from OLGA simulations, or from experts drawing "
            "the curves of events too rare to have been recorded. Only real instances belong to a "
            "physical well and can overlap another, so this viewer shows only those. Keep in mind "
            "when comparing sources that simulated and hand-drawn instances are clean by "
            "construction: no missing values, no frozen sensors, no noise, no outliers."
        ),
    ),
    (
        "The data is left as it was recorded",
        (
            "Real instances keep their frozen sensors, their missing variables and their outliers "
            "so that methods have to cope with them. A variable counts as <i>missing</i> when "
            "every one of its readings is missing in that instance, and as <i>frozen</i> when "
            "they all carry one single value; not always a fault, but a symptom of a sensor, "
            "configuration or network problem, and a variable that cannot show the pattern of an event. "
            "About two thirds of the variable-instance pairs of version 2.0.0 are missing and about "
            "a tenth frozen, which is why so many panels in this viewer read <i>not recorded</i> or "
            "<i>flat</i>. The Availability page counts them, sensor by sensor."
        ),
    ),
    (
        "Why so many sensors are dead",
        (
            "A well carries few sensors compared with a surface plant, because they are expensive "
            "and hard to reach: some sit more than a thousand metres under water or inside the "
            "production tubing. They are not always well calibrated, and a failed one can stay "
            "failed for a long time, since in some cases intervening costs more than living with "
            "it. The downhole gauge is the extreme case, and the cruel one: it is both the reading "
            "the analysts value most and the one most likely to be frozen or absent."
        ),
    ),
    (
        "Labels, and the three periods",
        (
            "The class column is 0 during normal operation, the number of the event once it has "
            "installed itself (its steady state), and that number plus 100 while it is installing "
            "itself (its transient period). An instance therefore holds up to three periods in "
            "order (normal, faulty transient, faulty steady state) and no instance carries more "
            "than one event. The transient period is the point of the whole design: it is the "
            "stretch where the dynamics of the event are still under way, so learning it means "
            "<i>predicting</i> the steady state rather than merely detecting it. Severe Slugging "
            "and Flow Instability have no transient period. Samples whose condition the experts "
            "could not establish are left unlabeled, about one in twenty of the dataset."
        ),
    ),
    (
        "The labels are expert judgement",
        (
            "Instances were labeled by Petrobras specialists in each event, and the thesis "
            "describes the onset of a transient as the moment <i>indicated by a specialist</i>. "
            "This is a matter of judgement, not a measurement. None of the documents reports how "
            "far two labelers would agree."
        ),
    ),
    (
        "The names are not settled",
        (
            "The 1.0.0 article opens its description of the events with a warning worth repeating: "
            "there is not always consensus on the names of these events or on what they mean, even "
            "among experts. The thesis says the same of the well states. What each class means "
            "here is what these documents say it means."
        ),
    ),
]

# What the availability page shows, for the help tab of the same name.
AVAILABILITY_INTRO = (
    "Every real instance carries every column the dataset declares, whether or not the well had "
    "the sensor, so what was actually recorded is a question of its own, and the "
    "<b>Availability</b> page answers it. Its rows are groups of instances (the fault classes, "
    "the wells, or the instances of one well or of one fault class, one by one) and its columns "
    "the sensors; every cell splits the samples of its row into three states, side by side from "
    "the left, so that the fuller the cell, the more of the sensor there is:"
)

# The kinds of cell of the availability page, in the order of the key: the
# swatch name (``heatmap.SWATCH_KINDS``), what to call it, what it means.
AVAILABILITY_STATES: list[tuple[str, str, str]] = [
    ("live", "Live", "Samples carrying a reading that moves over the instance."),
    (
        "filled",
        "Filled",
        (
            "Live samples that were not measured: the historian drew a straight line from one "
            "reading to the next, or carried the last reading forward until the next arrived. "
            "Shown, with <i>Measured vs filled</i> ticked, as the pale end of the live share, the "
            "solid part being the measurements; see <i>Measurements and the lines between "
            "them</i> below. On 3W 2.0.0 the pale part is most of every live cell."
        ),
    ),
    (
        "frozen",
        "Frozen",
        (
            "Samples carrying a reading, but one single value from end to end: a dead or "
            "disconnected instrument, which a count of readings alone would pass off as "
            "available. The rule is the one the instance window marks a plot <i>flat</i> by, so "
            "the two never disagree about a sensor. A valve state (the ESTADO variables) is never "
            "frozen: a valve that holds one position for a whole recording is a fact about the "
            "well, so those variables are only ever absent or live."
        ),
    ),
    (
        "absent",
        "Absent",
        "Samples carrying no reading: the well does not have the sensor, or lost it.",
    ),
    (
        "implausible",
        "Implausible",
        (
            "The mark of a reading no instrument could have produced, in at least one instance "
            "of the row: a negative absolute pressure or flow rate, a reading outside the band "
            "below, a magnitude beyond 1e8. Such a sensor is still live, since its readings are "
            "there and move, but what they say is not plausibly a measurement. Hover the cell for "
            "how many instances, and the plots of the instance window call the readings out in "
            "the same amber."
        ),
    ),
    (
        "order",
        "Out of order",
        (
            "The mark, in the bottom-right corner, of a pressure that reads out of order with "
            "another of its line in at least one instance of the row: downstream above upstream, "
            "which the flow cannot do (see <i>Pressures out of order</i> below). Each reading may "
            "be plausible on its own; the two contradict each other, so one of the instruments is "
            "not to be believed. Hover the cell for how many instances and for the other "
            "pressure. Known once the profile pass has run (the first tick of 'Measured vs filled' runs it, and its cache serves later sessions), since it reads every sample."
        ),
    ),
]

# Why each plausible range is what it is, per unit of ``config.PLAUSIBLE_RANGES``:
# the quantity, and the reasoning behind the survey of 3W 2.0.0 that found it.
PLAUSIBLE_RANGE_NOTES: dict[str, tuple[str, str]] = {
    "Pa": (
        "Pressures",
        (
            "Absolute pressures (table 3 of the paper), so a negative reading is impossible; 106 "
            "files of 3W 2.0.0 carry one, usually for the whole recording, a broken or mis-mapped "
            "tag the paper itself warns about. Zero is left alone: a sensor frozen at zero is "
            "another defect, and shows as frozen."
        ),
    ),
    "°C": (
        "Temperatures",
        (
            "The floor is below every genuine reading of the dataset (T-TPT reaches -33.8 °C "
            "during a blowdown) and the ceiling twice the hottest one (127.7 °C). The "
            "band catches the sentinels -999 and -99.99 the plant's information system leaks "
            "into the data, and T-PDG readings of 30,000 °C."
        ),
    ),
    "%": (
        "Choke openings",
        (
            "Percentages, so a reading below 0 or above 100 is impossible; one well reports an "
            "opening of -99.99 %, a sentinel."
        ),
    ),
    "m³/s": (
        "Flow rates",
        (
            "A rate is a magnitude, so a negative reading is impossible; no real instance of 3W "
            "2.0.0 carries one. The gas-lift flow rate (QGL), the only one recorded, reads 0 to "
            "4.31 m³/s; zero is left alone, since it is a closed gas lift. The ceiling is that "
            "largest reading about doubled and rounded up, as for temperatures: 10 m³/s, that is "
            "864,000 m³/d. The service pump rate (QBS) falls under the same range but is recorded "
            "by no real instance."
        ),
    ),
}
MAGNITUDE_NOTE = (
    "Every variable, these included, must also stay below <b>1e8</b> in magnitude: some sensors "
    "are frozen at absurd levels (one well reports P-PDG = -1.2e42 Pa for whole instances) or "
    "off by orders of magnitude (P-JUS-CKP around 1.4e9 Pa, that is 14,000 bar), and a survey of "
    "every instance of 3W 2.0.0 found a clean gap around this limit, the largest varying reading "
    "below it being 4.9e7 Pa and the smallest value above it 1.3e8, so the limit removes no real "
    "signal, which matters because genuine spikes are fault signatures. Valve states are held "
    "to this rule only."
)

AVAILABILITY_NOTES = [
    (
        "Pressures out of order",
        (
            "Fluid flows from high pressure to low, so along one line the pressure upstream must "
            "read above the pressure downstream. On the <b>production line</b> that is the "
            "downhole gauge above the tree, the tree above the platform upstream of the choke, and "
            "that above downstream of it (P-PDG, P-TPT, P-MON-CKP, P-JUS-CKP; a missing one is "
            "skipped and its neighbours compared). On the <b>service line</b>, which carries the "
            "gas lift down, it is the gas-lift header above the line past its choke (P-MON-CKGL "
            "above P-JUS-CKGL) and the annulus above the line at the platform (P-ANULAR above "
            "P-JUS-CKGL), the gas gaining the weight of its own column on the way down. A closed "
            "valve cuts a line in two, so a pair across a choke is compared only while the choke "
            "is open, and the annulus only while its master and wing valves are; a state not "
            "recorded counts as open. A pair is out of order where the downstream pressure "
            "exceeds the upstream one by more than 1 MPa in more than 1 % of the samples "
            "compared. The instance window draws those samples dashed in amber on both plots, "
            "and the cells of this page and the timeline bars wear an amber triangle in their "
            "bottom-right corner (once the profile pass has run). Only measurements "
            "take part: readings outside the plausible range and frozen sensors are left out. "
            "The rules come from a survey of every real instance of 3W 2.0.0, which also showed "
            "what not to ask: with gas flowing, the line downstream of the gas-lift choke reads "
            "above the tree in 87 of 110 instances (by a median of 5.5 MPa), since the gas enters "
            "the tubing far below the tree, and the annulus against the tubing goes either way. "
            "Under these rules 35 of the 1,119 real instances are out of order, among them a "
            "downhole gauge 18 MPa below its tree (WELL-00038), a tree transducer stuck near "
            "0.4 MPa (WELL-00037) and a downhole gauge dropping out to zero (WELL-00006)."
        ),
    ),
    (
        "Measurements and the lines between them",
        (
            "The dataset is sampled once a second, but the sensors were not read once a second. "
            "Melo noticed it on the normal instances of WELL-00001 (doctoral thesis, section "
            "4.2.5): the readings sit on straight lines between a few extremes, the plant's PI "
            "historian having interpolated linearly between the values it archived, and the "
            "scatter plot of two such series shows trajectories that are nothing but the ups and "
            "downs of two interpolations, creating spurious dynamics and spurious correlations, an "
            "impediment to the exploratory analysis he set out to do, so he stopped there. The "
            "viewer takes the direct route he considered too uncertain to take on the whole "
            "dataset: a straight line is a run of samples whose first difference is constant. A "
            "sample that lies on the line between its two neighbours, to one part in a million "
            "of the reading (the interpolation was evidently done in single precision), is "
            "<b>interpolated</b>; one that repeats the sample before it is <b>held</b>; the rest "
            "(the ends of every line and the first of every held run) are the "
            "<b>measurements</b>, one per value the historian archived. Interpolated and held "
            "together are <i>filled</i>. What the test cannot decide it counts as filled: a "
            "quantized sensor that repeats a value for three seconds, or climbs one step a "
            "second, draws the very lines the historian does. The valve states are not tested: "
            "a valve held in one position for hours is a fact about the well.<br><br>"
            "On 3W 2.0.0 the finding is stark. Over every live analog sensor of every real "
            "instance, <b>6 % of the samples are measurements</b>, 55 % are interpolated and "
            "39 % held, and the median interval between two measurements is 33 s. P-MON-CKP is "
            "read every 12 s, P-PDG every 13 s and T-TPT every 16 s where they are live; P-TPT "
            "every 100 s, T-JUS-CKP every two minutes, P-ANULAR every four. The consequence for "
            "any figure taken on the 1 Hz grid is what Melo saw: the lines make every series look "
            "far smoother than the process. The signal-to-noise ratio of T-JUS-CKP is 36,000 on "
            "the grid and 1.5 on its measurements; its autocorrelation takes seven minutes to "
            "halve on the grid and 73 s on the measurements. Wherever the viewer shows such a "
            "figure taken on the grid, it says so.<br><br>"
            "The viewer shows the measurements in four places. Every time series draws them as "
            "dots, with the line through every sample (which between two dots is exactly the "
            "historian's line) faint beneath: dense dots are a sensor read every second, sparse "
            "dots on a faint line a sensor filled in. <i>Measured vs filled</i>, on this page, "
            "splits the live share of every cell, and the Timelines' <i>Bar color: Measurements "
            "of a sensor</i> tints every bar by the share of its live samples that were measured. "
            "And <i>Measurements only</i>, in the toolbar of the signal views, counts and "
            "transforms the measurements alone: the histograms count what was read, and the "
            "spectrum becomes the Lomb-Scargle periodogram of the readings at their own instants, "
            "which needs no grid and is the honest spectrum of an irregularly sampled series, "
            "scaled so that it integrates to their variance as a density does. The pass that "
            "finds all this reads every file in full (about a minute and a half for the whole "
            "dataset, once, cached) and profiles every sensor of every instance and of every bar "
            "of the joined view as the merged recording it is, so that the joined view and the "
            "plain one never disagree."
        ),
    ),
    (
        "The 3W Toolkit's CleanSignals rule",
        (
            "The Toolkit's preprocessing step <code>CleanSignals</code> decides, per instance and "
            "per sensor, whether a signal is to be believed. It is fitted on the dataset: for "
            "every sensor it takes the mean and the spread (standard deviation) of the signal in "
            "every instance and puts bounds at the quartiles of those figures, three interquartile "
            "ranges out on either side; an instance whose mean or whose spread falls outside them "
            "loses the sensor, set to missing. The lower bound on the spread is floored at an "
            "absolute 1e-6, so a signal that never moves is always discarded. A sensor entirely "
            "missing in 60 % or more of the instances is dropped from all of them. "
            "The valve states are exempt."
            "<br><br>"
            "<i>Toolkit's CleanSignals</i>, on this page, applies the rule to the bars on show "
            "(the instances, or the joined bars, on which it is fitted afresh) and marks every "
            "cell in which the rule would discard the sensor in at least one instance of the row "
            "with a slash in its corner; the columns it would drop are greyed. The tooltip and "
            "the status bar say in how many instances, and for a single instance which bound it "
            "failed; a sensor's header says the bounds themselves. The two boxes beside move the "
            "IQR factor and the missing share, so the effect of a threshold can be read off the "
            "matrix. The Timelines offer <i>Bar color: Sensors the Toolkit's CleanSignals "
            "keeps</i>, every bar tinted by the share of its live sensors the rule keeps at the "
            "default thresholds, hovering it naming what the rule discards and why; and the "
            "header of every block of an instance window names the sensors the rule would discard "
            "in it, once the rule has been fitted anywhere. The rule needs only the mean, the "
            "spread and the emptiness of every sensor in every instance, which the profile pass "
            "holds, so it costs nothing once that pass has run. One difference from the Toolkit "
            "is kept on purpose: the profiles describe the plausible readings, so a sensor whose "
            "readings are instrument garbage is not discarded here by a mean of 1e42, it wears "
            "the amber mark instead, which says more."
        ),
    ),
    (
        "Sensor pairs",
        (
            "The <b>Sensor pairs</b> matrix puts the sensors on both axes and asks what no column "
            "of the first matrix answers: how often two sensors carry a reading <i>at the same "
            "instant</i>. Two sensors can each cover half a recording and never overlap, so a pair "
            "can be empty however well covered each of its sensors is, and a pair with little "
            "coverage is one no model can train on and a correlation nobody should trust, the "
            "point of Rabelo's figure 2.10. The diagonal is each sensor's own coverage, the "
            "<i>Over</i> box counts the pairs over every real instance or over those of one fault "
            "class or one well, and <i>Count</i> asks either that both sensors be live in an "
            "instance for it to count, or merely that both be recorded, frozen readings included, "
            "which is how Rabelo counts. Of the 351 pairs of 3W 2.0.0, 102 never carry a reading "
            "at the same instant. The footers cannot answer this one (a count of missing values "
            "says how much of a column is there, not which samples) so the first look reads the "
            "data, behind a progress dialog, and keeps the result in the cache.<br><br>"
            "<i>Join overlapping instances</i> changes the answer here rather than merely the "
            "arithmetic: a sensor one window did not record may be there in the window it "
            "overlaps, so two sensors that never share a sample inside one window can share "
            "plenty inside the recording the windows were cut from. And <i>Sensors: grouped by "
            "co-occurrence</i> lays the sensors out so that those recorded at the same instant "
            "sit together (a spectral seriation, the sensors placed on a line by the second "
            "eigenvector of the Laplacian of their overlap) which turns the blocks of the matrix "
            "into the sets of sensors a well carries or lacks together, and those sets are what "
            "say which subsets of the dataset a model could be built on at all."
        ),
    ),
    (
        "Sensor correlations",
        (
            "The <b>Sensor correlations</b> matrix asks the next question: of two sensors that "
            "are recorded together, how do they move together? Melo's exploratory methodology "
            "(doctoral thesis, section 4.1.5) reads the relations between the variables of a "
            "dataset three ways at once, and the <i>Coefficient</i> box offers the three. "
            "<b>Pearson</b> is the linear correlation, blue when positive and amber when negative, "
            "the cell full at ±1, computed exactly over every sample of the instances of the "
            "<i>Over</i> scope in which both sensors carry a plausible reading, pooled. <b>Mutual "
            "information</b> is a nonlinear one: the mutual information of the two sensors, "
            "estimated by nearest neighbours (Kraskov's estimator) on an even subsample of a few "
            "thousand of the same samples, turned into a coefficient between 0 and 1 by Laarne's "
            "normalisation √(1 − e⁻²ᴵ), which is the Pearson coefficient itself when the two are "
            "jointly Gaussian; two sensors bound by a curve rather than a line score high here and "
            "nothing on Pearson. <b>Nonlinear</b> is Zhang's coefficient, what the second says "
            "beyond the first, ρ_I × (1 − |ρ|). The title sums each into Melo's global coefficient "
            "over the sensors present (his equations 4.16 and 4.15), and a pair with fewer than "
            "300 co-valid samples is left blank rather than trusted. The valve states are left "
            "out: a position is not a measurement, and its two values would fill the matrix with "
            "coefficients of ±1 that say only which valves open together. The two nonlinear "
            "coefficients need the <i>analysis</i> extra.<br><br>"
            "The coefficients are taken on the grid as it is, with no moving average first. Melo's "
            "figures 4.11 and 4.26 show the coefficients of a process rising as a moving average "
            "grows, the noise hiding the relations, and the lines the historian drew between "
            "measurements (<i>Measurements and the lines between them</i>, above) were his reason "
            "to distrust any coefficient taken on the grid. What 3W 2.0.0 said is more sobering "
            "than either: pooled over a scope, the coefficients hardly moved with smoothing (the "
            "global linear coefficient of the whole dataset went from 0.420 with none to 0.424 at "
            "five minutes, and no pair of the severe-slugging class moved by more than 0.03) "
            "because a pooled coefficient is "
            "set by the levels the sensors sit at from one instance to the next, not by what "
            "happens between two measurements, which is why the viewer offers none. The lines' spurious dynamics live inside one "
            "instance, at the scale of seconds, which is where the Dispersions page looks. The "
            "caveat that does bite stands in the title: pooling the instances of a class, or of "
            "the whole dataset, mixes the levels of different wells into the coefficient, two "
            "sensors that both run higher on one well than on another correlate through the "
            "wells, not through the process, and with every well pooled the mutual-information "
            "coefficient of almost every pair reads 1.00, knowing one sensor's level being enough "
            "to know the well and so the other's, so a well's own scope is the one that shows the "
            "process, and there (WELL-00007) nearly every pair of pressures and temperatures "
            "correlates at ±0.99, through the well's shut-ins and restarts. The first look at a "
            "scope reads its instances in full, behind a progress dialog (about two minutes for "
            "the whole dataset); the result is kept for the session, not cached. <i>Join "
            "overlapping instances</i> pools the merged recordings of the bars instead of the "
            "windows, so that a sample two windows share is counted once."
        ),
    ),
    (
        "How the shares are counted",
        (
            "Shares are of samples: every sample of every instance in a row is absent, frozen or "
            "live, so the three parts of a cell add up to the whole cell, and a sensor recorded "
            "for part of an instance shows as partly absent. A sample two overlapping instances "
            "share is counted in both, once per instance; joining the instances first is not "
            "applied here yet. The last row folds every instance shown, and <i>Sensors: By "
            "coverage</i> orders the columns by it, the sensor live in the largest share of the "
            "samples first."
        ),
    ),
    (
        "Where the figures come from",
        (
            "The footer of every parquet file keeps, per column, a count of the missing values "
            "and the smallest and the largest value, so what every sensor recorded is read "
            "without reading the data, in the same pass that reads the labels, and cached with "
            "the catalogue. A file written without those figures is read in full instead."
        ),
    ),
    (
        "What 3W 2.0.0 shows",
        (
            "Four variables are recorded by no real instance at all: the service line's pressure "
            "and flow rate (P-JUS-BS, QBS), the pressure upstream of the production shutdown "
            "valve (P-MON-SDV-P) and the tree pressure downstream of the wing valve (PT-P). The "
            "downhole gauge is the cruel case the papers describe: its pressure (P-PDG) is frozen "
            "in more than half of the real instances and its temperature (T-PDG) in over a third. "
            "The pressure downstream of the production choke and the temperature upstream of it "
            "(P-JUS-CKP, T-MON-CKP) hardly exist outside the Hydrate in Production Line folder. "
            "And 113 instances on 18 wells carry a reading outside the plausible range, most often "
            "a negative pressure downstream of the gas-lift choke or a downhole gauge frozen at an "
            "absurd level."
        ),
    ),
    (
        "Why it matters for a model",
        (
            "Rabelo finds that the three sensors with the least coverage in the dataset (T-PDG, "
            "QGL, P-JUS-CKGL) are also the three his models lean on least, and the five with the "
            "most (P-TPT, P-PDG, P-MON-CKP, T-TPT, T-JUS-CKP) the ones they lean on most: a "
            "sensor has to be there to be learned from. His pipeline drops the columns that are "
            "entirely missing, forward-fills gaps of up to a minute, and drops an instance when "
            "more than half of its P-TPT samples are missing, which is what the absent share of "
            "a cell says such a rule would cost."
        ),
    ),
]

AVAILABILITY_SOURCES = (
    "Sources: the availability map of <b>G. Rozo</b> (the <i>main.ipynb</i> notebook of his "
    'fork of the 3W repository, <a href="https://github.com/GabrielRozo123/3W/blob/'
    'new_3w_datasets_overviews/dataset/demos/GabrielRozo/main.ipynb">github.com/GabrielRozo123/3W'
    "</a>, 2026), which measures the share of missing readings per sensor and event class on a "
    "sample of twenty events per class; the <b>final graduation project of G. Rabelo de "
    "Oliveira</b>, <i>Análise e modelagem integrada de dados de garantia de escoamento</i> "
    "(Universidade de Brasília, 2026, in <code>docs/papers</code>), whose section 2.3.2 measures "
    "the missing data per sensor and class (figure 2.8), the coverage of every sensor (figure 2.9) "
    "and of every pair of sensors (figure 2.10), and whose section 5.3.1 relates coverage to what "
    "the models learn; a survey of every instance of 3W 2.0.0 for the plausible ranges shown in "
    "this help; and the doctoral thesis of <b>A. Melo</b> (in <code>docs/papers</code>), whose section "
    "4.1.5 reads the relations between variables through the Pearson, mutual-information and "
    "nonlinear coefficients the correlation matrix shows, and whose section 4.2.5 found the "
    "historian's lines. This page counts the real instances only, and every one of them, where "
    "Rozo counts a sample of them and Rabelo every kind of instance."
)

MAP_INTRO = (
    "The other pages look at the real instances one well, one fault or one sensor at a time. The "
    "<b>Instances</b> page looks at all of them at once, from above: every instance (or, with "
    "<i>Join overlapping instances</i> ticked, every bar of the joined view, the merged recording) "
    "is one point, placed on the plane by what its sensors amount to, colored by its class, its "
    "well, its cluster, its typicality or the verdict of a one-class model, and one click away "
    "from its time series. The unit is the instance, never the window a pipeline cuts: 1,119 "
    "points, which a reader can hold in view. Nothing here is a model of the process; everything "
    "is an analysis of the catalogue, light enough to run again on every change of a box, and "
    "nothing is kept."
)

MAP_NOTES = [
    (
        "The representation",
        (
            "An instance becomes a point through its <b>descriptors</b>: for every sensor the "
            "mean, the spread, the median and the 5th and 95th percentiles, the skewness and the "
            "kurtosis, the autocorrelation time, the signal-to-noise ratio and the Gaussianity "
            "slope (the set Melo's methodology computes to characterise a variable), together "
            "with how it was measured, the share of its readings that are measurements and the "
            "interval between them. Each is one column, standardized to zero mean and unit "
            "spread, so that a pressure in pascal and a ratio weigh the same. A sensor enters "
            "only if it is live in at least half of the points: a sensor two wells carry says "
            "which two wells and nothing about the others, whose cells would all be made up. On "
            "3W 2.0.0 six sensors pass (T-TPT, P-TPT, P-ANULAR, P-MON-CKP, P-JUS-CKGL, T-JUS-CKP). "
            "A cell an instance lacks (the sensor absent or frozen there) takes the column's "
            "median, and the note under the map and the hover say how much of a point was made "
            "up that way. A valve state contributes its mean alone, the share of the time it was "
            "open.<br><br>"
            "<b>Descriptors <i>Interpolated</i>, or on the measurements.</b> The descriptors come "
            "twice from the profile pass, taken over the whole 1 Hz grid and over the "
            "measurements alone (see <i>Measurements and the lines between them</i> under Data "
            "availability). Over the grid, most of whose samples the historian drew between the "
            "readings it archived, the straight lines make every series look smoother than "
            "the process, the signal-to-noise ratio by orders of magnitude, so a map drawn from "
            "it is partly a map of how each sensor was archived. The <i>on</i> box chooses; "
            "the grid is what a pipeline reads, the measurements what the process did.<br><br>"
            "<b>Shape only</b> leaves the levels out (the mean, the spread and the quantiles), "
            "so that the level of a well, which is what separates wells most, does not place "
            "its instances, and what remains is how the signals move.<br><br>"
            "<b>DTW of a sensor, within a class</b> is the 3W Toolkit's own way of comparing "
            "instances, its clustering subpackage's distance: the dynamic time warping distance "
            "between the series of one sensor in two instances, which lines the two up allowing "
            "one to run ahead of or behind the other, so that two slugging cycles of different "
            "period still match. Each series is z-scored first (the toolkit's scaler) and "
            "averaged into 400 blocks, a matter of cost, since the distance costs the product of "
            "the two lengths and a six-hour instance has 21,600 samples. The blocks stay "
            "proportional to the length of the instance, so this is not the resampling of every "
            "instance to one common length, which changes what a shape is. A Sakoe-Chiba window "
            "of a tenth of the length keeps the alignment from running away. It is taken within "
            "one class, the class and the sensor chosen in the toolbar, and the points are then "
            "that class's instances alone."
        ),
    ),
    (
        "The embedding",
        (
            "<b>PCA</b> keeps the two directions of largest variance of the standardized columns "
            "and the axes say how much each carries; two components of a matrix with dozens of "
            "columns rarely carry more than a third, so the plane is a projection and two points "
            "close on it may be far apart. On a DTW representation PCA becomes the principal "
            "coordinates of the distances (classical multidimensional scaling), the same picture "
            "from the other end. <b>t-SNE</b> and <b>UMAP</b> keep neighbourhoods instead: points "
            "that are close stay close, far groups are laid out for legibility, so the distance "
            "between two groups means little and the axes have no unit. Both need their extras "
            "(<code>analysis</code>, <code>umap</code>) and take a few seconds on the whole "
            "dataset, with no progress dialog to cancel, so the pointer waits."
        ),
    ),
    (
        "Clusterings and their scores",
        (
            "The <i>Clustering</i> box groups the points, by the short list Siqueira's notebooks "
            "on 3W work through: <b>k-means</b> and a <b>Gaussian mixture</b> on the coordinates "
            "(k clusters), <b>agglomerative</b> clustering with average linkage and <b>DBSCAN</b> "
            "on the distances, DBSCAN reading its radius from the data (the median distance to "
            "the fifth neighbour) and leaving isolated points out, which shows as a faint grey. "
            "The status line scores the result three ways. The <b>silhouette</b> is how well "
            "each point sits in its own cluster against the nearest other, 1 for tight and "
            "well-separated clusters, near 0 for clusters that touch, negative for points "
            "misplaced. The <b>adjusted Rand index</b> and the <b>normalised mutual "
            "information</b> compare the clustering with a labeling the dataset already has, "
            "against the fault classes and against the wells: 1 for a clustering that is the "
            "classes (or the wells) under other names, about 0 for one unrelated to them. That "
            "is the question this page was built to ask: whether what places the instances is "
            "the event or the well they came from. The clusters are also offered as a bar color "
            "of the Timelines, in the same colors."
        ),
    ),
    (
        "Typicality",
        (
            "How ordinary an instance of its class each one is. In the representation chosen, "
            "the <b>medoid</b> of every class is the member whose distances to the others sum "
            "lowest (the most central instance the class actually has, which a mean need not "
            "be), and the typicality of an instance is its distance to that medoid, given as a "
            "rank inside its class: 1 for the medoid itself, 0 for the farthest member. It "
            "colors the points (full for the medoid, faint for the farthest), it is a bar color "
            "of the Timelines, and it is a sort order of the instance lists of the Faults and "
            "Features pages, whose tooltips carry it, so that the typical instances of an event "
            "can be drawn first and the outliers last, or the other way round. The figure "
            "depends on the representation: an instance typical in its levels may be atypical "
            "in its shape."
        ),
    ),
    (
        "The label audit",
        (
            "A one-class model of the normal instances (a radial-basis one-class SVM, the model "
            "Siqueira's notebooks use for novelty on 3W, fitted on the points of class 0 with "
            "5 % of them allowed outside its boundary, since the normal folder is not free of "
            "anomalies either) scores every point by its signed distance to that boundary. The "
            "list on the right is not a detector's output; it is an <b>audit of the labels</b>: "
            "class by class, the instances whose label disagrees with the verdict. For every "
            "fault class it lists the instances that <i>look normal</i> to the model, and for "
            "class 0 the instances that <i>look anomalous</i>. Either kind is worth a look (a "
            "fault the sensors chosen never register, a normal instance recorded during "
            "something, a label to question), and each is a click away. Under the <i>Novelty</i> "
            "coloring the points that look normal are blue, those that look anomalous amber, "
            "and a dark ring marks the disagreements. The score is also a sort order of the "
            "instance lists of the Faults and Features pages. The audit needs coordinates, so it "
            "rests under the DTW representation."
        ),
    ),
    (
        "The joined view",
        (
            "With <i>Join overlapping instances</i> ticked the points are the bars of the joined "
            "view (the instances of a well that overlap with labels that agree, read as the "
            "single recording they were cut from and profiled as such by the same pass), so a "
            "well recorded twice is one point where it was one recording, and the largest join "
            "of the dataset, seventy-one windows over six days, is one point. Everything on the "
            "page is computed again on the bars; the Timelines take the map's colorings only on "
            "the view the map was drawn on, and the instance lists of the other pages, which "
            "list instances, take its figures only from a map drawn on the instances."
        ),
    ),
]

MAP_SOURCES = (
    "Sources: the notebooks of <b>V. Siqueira</b> in the 3W repository, which cluster the real "
    "instances with k-means, Gaussian mixtures, mean shift, DBSCAN and agglomerative clustering, "
    "score them by silhouette, adjusted Rand index and normalised mutual information, embed them "
    "with t-SNE and UMAP, and detect novelty with a one-class SVM; the <b>clustering "
    "subpackage of the 3W Toolkit</b>, whose distance is the DTW between resampled, scaled "
    "series; and the doctoral thesis of <b>A. Melo</b>, whose characterisation of a variable the "
    "descriptors are."
)

MODEL_INTRO = (
    "The viewer displays what a model said; it does not train one. For a model's verdicts to be "
    "drawn onto the data, every verdict has to say which instance and which instant it is about, "
    "which is exactly what the 3W Toolkit's assessment export leaves out, so the viewer "
    "defines the format itself, the smallest one that says both, and ships an example of it with "
    "its provenance written down. <i>Load model outputs…</i>, in the main toolbar, opens a folder "
    "in that format and draws it everywhere an instance appears."
)

MODEL_NOTES = [
    (
        "The format",
        (
            "A set of outputs is a <b>folder</b> holding <code>model.json</code> and one parquet "
            "file per instance scored, laid out as the dataset is: "
            "<code>&lt;fault_class&gt;/&lt;instance&gt;.parquet</code>, the same folder number and "
            "file name as the instance it scores. <code>model.json</code> says what the model is: "
            '<code>name</code>; <code>kind</code>, <code>"detection"</code> for a model that '
            'says <i>anomalous or not</i> and <code>"classification"</code> for one that names '
            "the event by its 3W class number; <code>labels</code>, the meaning of every label "
            'value the files carry, such as <code>{"0": "normal", "1": "anomalous"}</code>; '
            "a <code>description</code>; and <code>provenance</code>: who produced the outputs, "
            "with what script and what parameters, on which dataset version, when. Each parquet "
            "file has the <code>timestamp</code> of every sample scored as its index, an integer "
            "<code>label</code> column and, optionally, a float <code>score</code> column, the "
            "model's own figure in its own unit, larger meaning more anomalous. A model need not "
            "score every sample of an instance, nor every instance; what it did not score is "
            "simply not drawn."
        ),
    ),
    (
        "Agreement",
        (
            "Every verdict is judged against the experts' <code>class</code> labels over the "
            "stretches where both said something. A detection model agrees where it says "
            "<i>anomalous</i> and the label is a fault, transient or steady, and where it says "
            "<i>normal</i> and the label is 0; a classification model where its class equals the "
            "fault the label names (a transient label counting as its fault), or both are 0. "
            "Stretches the experts left unlabeled, and stretches the model did not score, are not "
            "compared. The share of the compared time in agreement is the instance's "
            "<b>agreement</b>, a figure between 0 and 1 that the pages color and sort by; the "
            "figure is computed from the label runs the catalogue already holds, so loading a set "
            "of outputs costs only reading them."
        ),
    ),
    (
        "Where it shows",
        (
            "In every <b>instance window</b> a third band, <i>model</i>, appears under the class "
            "band of every block the model scored: plain, in the live blue, where the verdict "
            "agrees with the label under it, <b>amber where it disagrees</b>, faint where the "
            "experts left the stretch unlabeled; hovering it names the verdict, and the header of "
            "the block gives the agreement. On the <b>Timelines</b>, <i>Bar color: Agreement with "
            "the model outputs</i> tints every bar by it, faint for none and full for all, empty "
            "where the model scored nothing, a joined bar weighted by the time compared in each of "
            "its instances. On the <b>Instances map</b>, <i>Color by: Model agreement</i> does the "
            "same for the points. On the <b>Faults</b> and <b>Features</b> pages the instance lists "
            "sort by it (<i>Sort: Agreement with the model outputs</i>, the instance the model "
            "disagrees with most first), every tooltip carries it, and <i>Shade by: Model "
            "outputs</i> shades the label periods behind the small plots with the model's verdicts "
            "instead of the experts' (a detector's <i>anomalous</i> drawn as the instance's own "
            "fault and its <i>normal</i> as normal operation, a classifier's classes as "
            "themselves), so that where the two differ is seen against the trace."
        ),
    ),
    (
        "The example, and its provenance",
        (
            "<code>examples/model_outputs/pca_control_chart_wells_1_4_6_7</code> holds the outputs "
            "of a <b>PCA control chart</b> over the 319 real instances of four wells of 3W 2.0.0: "
            "the oldest tool of multivariate process monitoring, and the one Melo's thesis and his "
            "BibMon package build on. One model was fitted per well, on every sample of that "
            "well's Normal Operation instances over the analog sensors live in all of them, and "
            "followed "
            "two statistics along every instance of the well, Hotelling's T² (the distance of a "
            "sample inside the model's plane) and Q (its distance off the plane), calling a sample "
            "anomalous when either exceeded the 99th percentile of its statistic over the training "
            "samples; the score is the larger of the two ratios to their limits. It was produced by "
            "<code>scripts/pca_control_chart.py</code>, whose command, parameters and fitted limits "
            "are written in the example's <code>model.json</code>. It agrees with the labels 98 % "
            "of the time on the normal instances of all four wells, and between 100 % and 5 % on "
            "their fault instances: the same method on the same event, flow instability, reads "
            "100 % on WELL-00007 and 5 % on WELL-00001, because a model fitted on two normal "
            "instances of a ten-sensor well draws a tight normal region while one fitted on "
            "ninety-three instances of a five-sensor well draws a wide one. <b>An agreement figure "
            "says as much about a well's normal data as about the event</b>, wherever this viewer "
            "shows one. It is one producer of the format among many: the U-Net segmentation of Lopes "
            "<i>et al.</i>, the Toolkit's own models with an export that carries the instance and "
            "the instant, or a hand-labeled review would all fill it the same way. The outputs of a "
            "model are stored and shown; the model itself is not built into the viewer."
        ),
    ),
]

MODEL_SOURCES = (
    "Sources: the PCA control chart as A. Melo's doctoral thesis (chapter 4) and his BibMon "
    "package apply it; the 3W Toolkit's <code>ModelAssessment</code> export, whose columns are "
    "<code>true_values</code>, <code>predictions</code>, <code>model_name</code>, "
    "<code>task_type</code> and <code>timestamp</code> and which therefore cannot be drawn onto "
    "the data; the U-Net segmentation of Lopes <i>et al.</i> (CILAMCE), a producer of per-sample "
    "verdicts this format could carry."
)

DISPERSION_INTRO = (
    "The <b>Dispersions</b> page draws two sensors against each other, every sample of the "
    "instances of a scope one dot (over every real instance, one fault class or one well, as "
    "instances or as the joined bars), with the density of the samples shaded behind the dots. "
    "It is the scatter plot of Melo's exploratory methodology made readable: a static scatter of "
    "a million points is a smear, and this one names the instance and the instant of every dot "
    "on hover and lights up every other dot of that instance, opens the instance on a click, "
    "colors the dots by class, by well or by label period, switches the label periods on and "
    "off, thins itself to the measurements alone and shows what a moving average does to the "
    "cloud."
)

DISPERSION_NOTES = [
    (
        "What the cloud shows, and what the historian drew",
        (
            "Melo's scatter plots of two 3W variables (doctoral thesis, section 4.2.5, figure 4.55) "
            "were where he saw the historian's hand: the cloud of two interpolated series is the "
            "trajectories of the two interpolations, straight segments between the few instants "
            "that were measured: spurious dynamics, a relation between two straight lines rather "
            "than between two readings. No pooled coefficient betrays them, because a pooled "
            "coefficient is set by the levels the sensors sit at from instance to instance. Every scatter plot does, and hovering a dot "
            "brings every other dot of its instance forward while the rest of the cloud fades, so "
            "one recording's trajectory can be followed through it. So the page offers "
            "the cloud two ways. Every sample as a dot, which is the grid a pipeline reads; and "
            "<i>Measurements only</i>, the samples at which both sensors were actually read, a few "
            "per cent of the dots, from which the straight trajectories vanish and the process "
            "remains. The "
            "<i>Density</i> behind the dots is a two-dimensional histogram of every sample kept, "
            "darker where more fall, on a logarithmic scale, so that a hundred thousand dots on "
            "one spot read as the spot they are; <i>Color by: Density</i> shows it alone. On "
            "3W 2.0.0 the densest cell of a common pair holds a tenth of all the samples, which "
            "no cloud of dots can say.<br><br>"
            "The measurements carry a caveat of their own. A historian archives a reading when it "
            "has moved enough, so the instants at which <i>both</i> sensors were archived are "
            "instants at which both moved, and the cloud of the measurements favours the relation "
            "between them: over the severe-slugging instances P-TPT × T-TPT reads +0.40 on every "
            "sample and +0.95 on the 5 % at which both were measured; over the whole dataset −0.03 "
            "and +0.41. Neither figure is the wrong one (the first is what a pipeline trained on "
            "the grid sees, the second what the instruments reported when they reported), and "
            "the page exists so that both can be looked at. The label periods matter as much: on "
            "WELL-00007 every pair of pressures and temperatures correlates at ±0.99 over every "
            "sample and at ±0.2 to ±0.4 over the steady state of its faults alone, the pooled "
            "figure being about the well's shut-ins and restarts."
        ),
    ),
    (
        "Scopes, periods, colors",
        (
            "<i>Over</i> is the scope, and it carries the caveat of every pooled view: two clouds "
            "side by side may be two wells rather than one relation, since wells run at different "
            "levels, so a well's own scope is the one that shows the process alone, and "
            "<i>Color by: Well</i> is how to tell the two apart in a class's cloud. <i>Label "
            "periods</i> choose the samples by what the experts labeled the well as doing at that "
            "instant: a fault's steady state alone shows the relation under the fault, normal "
            "operation alone the relation the fault departs from, the transient the path between; "
            "<i>Color by: Label period</i> draws the three in one cloud. <i>Color by: Fault "
            "class</i> colors every dot by the folder of its instance. <i>Join overlapping "
            "instances</i> reads the merged recordings of the bars instead of the windows, so that "
            "a sample two windows share is drawn once."
        ),
    ),
    (
        "Reading and cost",
        (
            "The first look at a scope reads its instances in full, behind a progress dialog, "
            "every analog sensor at once, and keeps an even subsample of the rows for the session: "
            "400,000 rows in all, spread evenly over the instances, one row in a few for a single "
            "well and one in fifty for the whole dataset (about two minutes to read), so that "
            "changing the sensors, the coloring, the periods or the measurements filter is "
            "instant. At most 150,000 of the rows are drawn as dots, evenly; the density counts "
            "them all. The caption "
            "says how many dots of how many samples of how many instances are on show, one in how "
            "many, and the Pearson coefficient over those very samples, so that the cloud and the "
            "correlation matrix can be read against each other."
        ),
    ),
]

DISPERSION_SOURCES = (
    "Sources: the doctoral thesis of <b>A. Melo</b> (in <code>docs/papers</code>), whose section "
    "4.2.5 reads the scatter plots of pairs of 3W variables and finds the historian's "
    "interpolation in them, and whose section 4.1.5 reads the relations between variables through "
    "the coefficients the correlation matrix shows; the readings the page draws as dots are the "
    "measurements found by the rule of <i>Measurements and the lines between them</i> under Data "
    "availability."
)

WINDOWS_INTRO = (
    "The <b>Windows</b> page shows one sensor of a well the way a model of the 3W reads it: cut "
    "into windows of a fixed number of samples (256, 512 or 1024 seconds), each window carrying "
    "one label. The division is made here, in software, from the instance files: choose a well "
    "and a sensor and every instance of the well is read, behind a progress dialog, and cut. "
    "The windows are listed in a table, laid out as thumbnails page by page, each shaded in the "
    "color of its label and captioned with its name, and placed along the well's time axis; "
    "the window selected is drawn large beside the instance it was cut from. <i>View</i> swaps "
    "the signal for one statistic of every window, among those the viewer already computes."
)

WINDOWS_NOTES = [
    (
        "The four rules of the division",
        (
            "<b>Exact size.</b> Every window holds exactly the number of values chosen. "
            "<b>One label.</b> An instance is split into runs of constant label (normal "
            "operation, every fault's steady state, every transient and the unlabeled stretches "
            "are distinct labels), and every run is cut into consecutive windows of its own, so "
            "no window passes from normal operation to a transient or a fault and the label of a "
            "window is the label of every one of its samples. <b>Zero padding.</b> When the end "
            "of a run does not fill a window, the last window of the run is completed with zeros "
            "at its end, cross-hatched on every plot; its real samples are counted, and its "
            "statistics are taken over them alone. <b>No overlap.</b> With <i>Remove overlaps</i> "
            "ticked, the instances of the well are walked in chronological order and each loses "
            "the samples an earlier one already covered, so no instant is in two windows: on 3W "
            "the first, unlabeled hour of an instance is usually a copy, sample by sample, of the "
            "last hour of the one before (18.9 % of the samples of WELL-00002's P-TPT). The "
            "instance plot of the window selected hatches that head. Unticked, every instance is "
            "cut whole. The rules are those of the <code>3w_estudo</code> division, which writes "
            "the windows to disk and audits them; here nothing is written, and a well's 5.7 "
            "million samples of one sensor read and cut in about two seconds."
        ),
    ),
    (
        "Labels and colors",
        (
            "Every window is written with its label, the code the <code>class</code> column "
            "carries and its name (<i>0 · Normal Operation</i>, <i>102 · Spurious Closure of "
            "DHSV - Transient</i>, <i>2 · Spurious Closure of DHSV</i>, <i>— · unlabeled</i>), in "
            "the table, above every thumbnail and above the window selected, and shaded in the "
            "colors of the instance window's class band: a fault's steady state in its hue at "
            "full strength, its transient lighter, a normal stretch in the faint hue of its "
            "instance's folder, an unlabeled one grey and hatched. The strip above the grid "
            "draws every window passing the filters in its label's color, a tone apart from its "
            "neighbour so that consecutive windows can be told apart when zoomed in."
        ),
    ),
    (
        "Filters and statistics",
        (
            "<i>Instance</i> keeps the windows of one instance, <i>Fault</i> those of one fault "
            "folder, <i>Label</i> those of one label; <i>Hide unlabeled</i>, <i>Complete windows "
            "only</i> (no padding) and <i>No missing readings</i> thin them further. <i>View</i> "
            "offers one statistic of every window among those the viewer already computes: the "
            "instance window's statistics table (mean, median, standard deviation, minimum, "
            "quartiles, maximum, skewness, excess kurtosis) and the Timelines' descriptor "
            "coloring (autocorrelation time, signal-to-noise ratio, Gaussianity slope), taken by "
            "the same <code>describe</code> over a window's real samples, its padding left out "
            "and its missing readings dropped. The first statistic asked of a cut describes every "
            "window at once and the others are then instant. The statistic is drawn one point "
            "per window along the well, colored by label period, beside its distribution per "
            "period and the separation of normal from event windows, |AUC − 0.5| · 2, from 0 "
            "(indistinguishable) to 1 (split)."
        ),
    ),
]

WINDOWS_SOURCES = (
    "Sources: the division of <code>3w_estudo</code> (<code>w3e/divisao.py</code>, audited by "
    "<code>scripts/verificar_janelas.py</code>) and its <i>Janelas</i> tab, whose separation of "
    "normal from event windows is the one drawn here; the statistics are the viewer's own "
    "descriptors, under <i>Instance window</i> and <i>Timelines page</i> in <i>Using the "
    "viewer</i>."
)

# How to work the viewer, shown in both windows.
USAGE = {
    "Timelines page": [
        (
            "Every plot is one well; every bar is one real instance, from its first to its last "
            "sample. Bars that overlap in time are stacked, so the stack level is how many "
            "instances cover that moment. The line above a plot counts the well's instances and "
            "samples (a shared sample once per instance, or once when joined) and, under a bar "
            "color that names a sensor, that sensor's measurements on the well once the profiles "
            "have been read."
        ),
        (
            "Hover a bar to outline it, outline the instances it overlaps, hatch the stretch they "
            "share and dim the rest. The status bar names them and the color key lights up the "
            "matching entries. Rest the pointer on the bar for a tooltip with its start, its end "
            "and its duration; a joined bar spans from its first instance's start to its last's "
            "end."
        ),
        "Click a bar to open the time series of that instance and of every instance it overlaps.",
        (
            "Click an entry of the color key to show only the wells that recorded that fault; "
            "click it again, or the button at the right of the toolbar, to show them all again."
        ),
        (
            "Click the title of the color key, or press Ctrl+L, to retract it to that one line and "
            "give the grid the room. Retracted it still answers hovering: the entries of the "
            "instance under the pointer, and of the instances it overlaps, pop into the title row."
        ),
        (
            "A well is recorded in bursts separated by months of silence, so the silences are "
            "collapsed to narrow dashed blanks. The time scale stays uniform everywhere else: bar "
            "length is duration, and two bars overlap on screen exactly when the instances overlap "
            "in time. Untick 'Compress silences' for a true calendar axis."
        ),
        (
            "Tick 'Join overlapping instances' to merge the instances of a well that overlap in "
            "time into one bar wherever their labels agree on the shared stretch (an unlabeled "
            "sample agrees with anything). Instances whose labels disagree there stay apart, so "
            "the overlaps left are exactly the labeling conflicts. A bar joined from instances of "
            "several fault folders is striped with every folder's color and says how many more "
            "instances it joins after its timestamp; clicking it opens them as the single "
            "continuous recording they were cut from."
        ),
        (
            "Tick 'Stitch instances' to see how the levels of a well changed from one recording "
            "to the next: the joined bars of every well are laid end to end, the silences between "
            "them left out, so each well becomes one bar holding its whole history, a solid line "
            "marking each stitch. Clicking it opens every reading of the well as one recording, on "
            "an axis that keeps the real timestamps and jumps at each stitch. The stitch joins "
            "the instances first, so it ticks 'Join overlapping instances' and holds it ticked; "
            "unticking the stitch leaves the join as it was before. 'Compress silences' rests "
            "meanwhile, there being no silence left. The descriptor and CleanSignals colorings "
            "judge one recording at a time and leave a stitched bar empty. A well of hundreds of "
            "instances takes some seconds to open this way (WELL-00002, 4.6 million samples, "
            "about ten)."
        ),
        (
            "'Bar color: Availability of a sensor' tints every bar by the share of its samples in "
            "which the chosen sensor is live, faint for a few and full for all, grey under the "
            "frozen key for a sensor that never moved, empty for one never recorded, so the grid "
            "becomes the history of that sensor on every well: an era of absence, or a scattering "
            "of it. The key above the grid changes with it."
        ),
        (
            "A small amber triangle in the corner of a bar marks an instance in which a sensor "
            "reads outside its plausible range; the status bar names the sensors. The same "
            "triangle in the bottom-right corner marks pressures read out of order along their "
            "line, the status bar naming the pairs. Known once the profile pass has run (the first tick of 'Measured vs filled' runs it, and its cache serves later sessions), since it reads every sample. Tinted by one sensor, the marks "
            "are for that sensor alone."
        ),
        (
            "'Bar color: Measurements of a sensor' tints every bar by the share of the sensor's "
            "live samples that were actually measured rather than filled in by the historian, "
            "faint for a few, full for all, so an era in which a sensor was archived every two "
            "minutes reads apart from one in which it was read every second. Hover a bar for the "
            "share and the interval. The first time, it reads every instance in full behind a "
            "progress dialog and keeps the result in the cache."
        ),
        (
            "'Bar color: Descriptor of a sensor' tints every bar by one figure of the sensor's "
            "series (the time its autocorrelation takes to halve, its signal-to-noise ratio, the "
            "slope of Zhang's Gaussianity regression, its skewness or its kurtosis, Melo's "
            "characterisation of a variable), ranked among the bars on show, faint for the "
            "smallest and full for the largest, so that the grid shows which recordings of a "
            "sensor were slow, noisy, heavy-tailed or skewed. The 'on' box takes the figure over "
            "the whole 1 Hz grid ('Interpolated', which is what a pipeline reads) or over the "
            "measurements alone; interpolated, the historian's lines inflate the autocorrelation "
            "time and "
            "the signal-to-noise ratio, and the key and the hover say so. Hover a bar for both "
            "values and the rank."
        ),
    ],
    "Availability page": [
        (
            "Every column is a sensor and every row a group of instances: choose the fault "
            "classes, the wells, or the instances of one well or of one fault class in the Rows "
            "box. The last row folds every instance shown."
        ),
        (
            "A cell splits the samples of its row into live, frozen and absent, left to right, in "
            "the colors of the key at the right of the toolbar; the fuller the cell, the more of "
            "the sensor there is. A small triangle in its top-right corner marks a reading "
            "outside the plausible range, one in its bottom-right corner a pressure read out of "
            "order with another of its line."
        ),
        (
            "Hover a cell for the shares, the instance counts, the extreme readings and the "
            "implausible ones; hover a sensor's name for what it is and its plausible range; "
            "hover a row's label for what the row holds. A tooltip carries the figure the cell "
            "draws, where the pointer is, as a printed availability map writes it inside the "
            "cell; the status bar carries that and the rest."
        ),
        (
            "The 'Matrix' box switches to 'Sensor pairs': the sensors on both axes, every cell "
            "the share of the samples in which both carry a reading at the same instant. The "
            "'Over' box counts them over every real instance or over one fault class or one well, "
            "and 'Count' asks either that both sensors be live or merely that both be recorded."
        ),
        (
            "In the pair map 'Sensors' offers a third order, 'Grouped by co-occurrence', which "
            "puts the sensors recorded at the same instant next to one another, so that the "
            "blocks of the matrix read as the sets of sensors a well carries or lacks together "
            "rather than as a ranking. 'Join overlapping instances' applies here too, and changes "
            "what the map says: a sensor one window missed is filled in by the window it overlaps."
        ),
        (
            "The 'Matrix' box's third entry, 'Sensor correlations', colors every pair of sensors "
            "by how they move together over the samples of the 'Over' scope, pooled: blue "
            "positive, amber negative, full at ±1. 'Coefficient' chooses Pearson, the "
            "mutual-information coefficient or Zhang's nonlinear coefficient (the last two need "
            "the analysis extra). Hover a cell for all three coefficients and the co-valid sample "
            "count. The first look at a scope reads "
            "its instances behind a progress dialog."
        ),
        (
            "Click a fault class or a well, on its label or on any of its cells, to see its "
            "instances one by one; the Rows box takes you back. Click an instance, on its label "
            "or on a cell, to open its time series with that sensor drawn."
        ),
        (
            "'Sensors: By coverage' orders the columns by the share of what is on show in which "
            "each sensor is live, largest first."
        ),
        (
            "'Cells' splits each cell by samples, so that a six-day instance weighs more than a "
            "six-hour one (as Rabelo counts), or by instances, each weighing the same (as Rozo "
            "counts); the two disagree because instances range from hours to days."
        ),
        (
            "'Available from' sets the share of its samples a sensor needs readings in to count "
            "as available in an instance at all; below it the instance counts as absent for that "
            "sensor, readings and all. Rabelo's pipeline drops an instance whose P-TPT is more "
            "than half missing: 50 % shows what that rule keeps."
        ),
        (
            "'Join overlapping instances' counts the bars the timelines draw when joined: "
            "overlapping instances whose labels agree, read as the single recording they were cut "
            "from, in which a sample two windows share is counted once and a sensor one window "
            "missed is filled in by another. The footers of the files cannot say which instants "
            "two windows share, so the first tick reads the data, behind a progress dialog, and "
            "keeps the result in the cache."
        ),
        (
            "'Measured vs filled' splits the live share of every cell into the samples that were "
            "measured, solid, and the samples the historian filled in between measurements, pale, "
            "which is most of every live cell on 3W 2.0.0. The cell's tooltip and the status bar "
            "then say the share and the interval between measurements. The split is of samples, "
            "so it rests while the cells count instances; the first tick reads every instance in "
            "full, behind a progress dialog, and keeps the result in the cache."
        ),
    ],
    "Faults page": [
        (
            "Pick a fault: every real instance of it, from every well, is drawn in the color of "
            "its well on a time axis that starts where the event begins in it, so the shapes line "
            "up whatever the clock said; 'Align at' chooses that moment, the onset of the "
            "transient, of the steady state, or the start of the recording."
        ),
        (
            "A well keeps its color whatever fault is on show, so that the same line means the "
            "same well from one fault to the next; the list on the right is the key. The colors "
            "are deliberately not the fault hues: since both codes are drawn in one plot (a "
            "trace over the shading of its label periods, the outline of a histogram over stacks "
            "in the fault's own hue), the wells are separated from the faults by lightness rather "
            "than by hue, deeper than every fault hue here and paler than every one of them in "
            "the dark mode."
        ),
        (
            "'Layout' chooses among three. <b>Small multiples</b>, the default, give every "
            "instance a plot of its own in a grid under a heading per feature (which counts the "
            "samples drawn in the window of hours and how many of them were measured), each with "
            "its own value axis and its label periods shaded behind the trace (hatched where nobody "
            "labeled it, as everywhere else in the viewer), so that two dozen shapes can be read "
            "one against the next; 'Columns' sets the width of the grid and 'Axis' "
            "puts every plot on its own value axis or all of them on one, which says how far "
            "apart the levels are and flattens most of the plots saying it. <b>Overlaid</b> draws "
            "them all on one set of axes, and <b>Overall</b> pools them into one curve first, off "
            "the time axis only (see <i>Signal views</i>). The grid opens on the stretch of time "
            "most of the instances cover, so that one instance recorded for days does not leave "
            "every other plot a sliver; Ctrl + wheel zooms out to the rest."
        ),
        (
            "An instance whose labels never reach the moment chosen cannot be aligned on it and "
            "is greyed out in the list on the right. Beyond two dozen instances the earliest are "
            "ticked to start with, and the grid draws at most four dozen of them; tick and untick "
            "to choose, All and Clear do it at once."
        ),
        (
            "'Normalize per instance' scales every series to its own level, each reading as "
            "standard deviations from the mean of that sensor over the whole instance, which is "
            "how Rabelo's pipeline normalizes: wells run at different levels, and the shape of "
            "the change is what the instances share. 'Show … h before/after' narrows the plots "
            "to the hours around the onset; at zero, everything recorded is drawn."
        ),
        (
            "Hover a line to bring it forward and name it, with the label, the well status and the "
            "readings of that instance at that moment in the status bar; pointing at an instance "
            "in the list does the same. Readings outside the plausible range are left out of the "
            "value axis, so one broken gauge does not flatten every other line; the instance "
            "carrying them wears the ⚠ in the list."
        ),
        (
            "Click a plot to open the instance window of its instance on that feature: a small "
            "plot opens the one instance it holds, an overlaid plot the line the hover has named; "
            "a pooled curve stands for many instances and opens none. Click an instance's name in "
            "the list to open its window on its default features; its check box still ticks it."
        ),
        (
            "The page opens on the analog sensors of the seabed (P-ANULAR, P-TPT, T-TPT), the same "
            "for every fault. 'Topside', 'Seabed' and 'Subsurface' tick every recorded sensor measured at one placement of the production system: on the platform above water (the production choke and shutdown valve, the gas-lift and service lines), at the christmas tree on the seabed, and in the well below it. A second click clears the placement; the boxes add up, and a box shows half ticked while only some of its sensors are selected. Which part of the system matters for an analysis is left to the user; the variables the papers read each event in are listed in the Fault classes tab. Features no instance of the fault recorded are "
            "greyed out."
        ),
    ],
    "Features page": [
        (
            "The faults page fixes a fault and asks what its instances did to each sensor; this "
            "page turns the question round. Pick a <b>Feature</b>, one sensor, and every fault "
            "class gets a section, so that what a gauge reads under a hydrate can be set beside "
            "what the same gauge reads under severe slugging and under normal operation. That is "
            "the feature-wise grouping of the catalogue: the timelines are the well-wise one and "
            "the faults page the fault-wise one."
        ),
        (
            "The count beside a sensor's name is how many real instances recorded it; one no "
            "instance recorded is greyed out. The page opens on the sensor the most instances "
            "record a <i>moving</i> reading of, which keeps a valve state out of the way of the "
            "default: nearly every instance carries one, and a valve holding its position for a "
            "whole recording would open the page on a row of flat lines. <b>Well</b> narrows "
            "everything to one well, so that the classes are compared at one place and one set of "
            "instruments."
        ),
        (
            "The classes on the left choose the sections and are the color key; the instances on "
            "the right choose what is read from disk. The earliest few of each class are ticked "
            "to start with: of <i>each</i> class rather than the earliest few overall, since a "
            "class whose instances all come later would otherwise open with nothing in its "
            "section, and the grid likewise spends its cap per class."
        ),
        (
            "<b>Layout</b> means something particular here. Small multiples give every instance a "
            "plot of its own in a grid under a heading per class (with the samples drawn and how "
            "many were measured); because the heading already "
            "names the class, the trace takes the neutral color and the class hues are left to "
            "the shading of the label periods behind it and to the stacks of a histogram, which "
            "a line of the same hue would vanish into. <b>Overlaid</b> puts every class on one "
            "set of axes, each instance in its class's color, which is the view the page exists "
            "for and the natural one for histograms and spectra, where the question is whether "
            "the classes sit at different values or peak at different periods."
        ),
        (
            "'Align at' starts on the start of the recording, the one anchor every class has: "
            "normal operation has no transient and no steady fault state, so anchoring on either "
            "leaves every normal instance greyed out."
        ),
        (
            "Click a plot, or an instance's name in the list, to open its instance window, as on "
            "the Faults page: from a plot on the sensor on show, from the list on its default "
            "features."
        ),
    ],
    "Instance window": [
        (
            "One block per bar of the overview, stacked in chronological order on one shared time "
            "axis, so the stretches they share line up vertically. The band at the very top marks "
            "those stretches. A block's header names it on its first line and says what it holds "
            "on the second: its samples, the time it spends in normal operation, in the transient, "
            "in the steady state and unlabeled, and how many of its samples the historian archived "
            "for every ticked feature."
        ),
        (
            "A bar the overview has joined opens as one block: its instances are read as the "
            "single continuous recording they were cut from, drawn as one series over one set of "
            "bands, with a dashed line where each further instance begins. Every instant appears "
            "once, and what one window says nothing about the others fill in, so the label band "
            "of a merged recording carries far less Unknown than its instances did apart, which "
            "is what a model trained on it would see, unlabeled samples being dropped. Each "
            "stretch keeps the color of the file that labeled it, so a normal period labeled by a "
            "Normal Operation file stays that file's color inside a recording that goes on to "
            "develop a fault."
        ),
        (
            "'Join overlapping instances' is in this window's toolbar too, and merges exactly the "
            "instances on screen: the group the window opened on is all it is about, so two of "
            "them that overlap only through an instance outside the window stay apart, and what "
            "the well as a whole would join is not brought in. It changes this window alone, and "
            "turning it off lands where it started. A window opened from a bar the overview had "
            "already merged is showing that merge, so its box is ticked and disabled; so is one "
            "opened from a stitched well, whose recordings are laid end to end on an axis that "
            "jumps at each solid line, the silences left out."
        ),
        (
            "Tick features on the left to add a plot of them to every instance. The plots of one "
            "feature share their value axis, so the same reading sits at the same height in all of "
            "them. 'Features' in the toolbar, beside 'Join overlapping instances', hides that "
            "panel to give the plots its width; the choice survives a join toggled or a new group "
            "opened."
        ),
        (
            "'Theme', in the toolbar, paints this window alone light or dark, whatever the main "
            "window is in; 'As the main window' follows it again. A window with a theme of its own "
            "ignores the main window's switches."
        ),
        (
            "'Normalize per instance', in the Views row, draws every trace as z-scores over its own "
            "block, readings outside the plausible range left out first, so that blocks recorded at "
            "different levels share one value axis and their shapes compare; the histograms, the "
            "spectra and the readout follow, and the figures beside each trace stay in its unit."
        ),
        (
            "'Topside', 'Seabed' and 'Subsurface' tick every recorded sensor measured at one placement of the production system: on the platform above water (the production choke and shutdown valve, the gas-lift and service lines), at the christmas tree on the seabed, and in the well below it. A second click clears the placement; the boxes add up, and a box shows half ticked while only some of its sensors are selected. Which part of the system matters for an analysis is left to the user; the variables the papers read each event in are listed in the Fault classes tab. A window opens on the analog sensors of the seabed (P-ANULAR, "
            "P-TPT, T-TPT), the same for every event, unless it was opened on one sensor (from the "
            "availability page, or from a plot of the Faults or Features page) or on two (from a "
            "dot of the Dispersions page, its X and Y), or none of them was recorded, when it "
            "opens on the first recorded feature."
        ),
        (
            "A crosshair follows the pointer through every plot, and the status bar reads out the "
            "label, the well status and the selected readings of each instance at that moment."
        ),
        (
            "The bands and the plot backgrounds carry the colors of the overview bars. A stretch "
            "nobody labeled is hatched instead of merely grey, so it cannot be taken for one of "
            "the two faults whose own color is grey."
        ),
        (
            "Each panel reports the total variation of the signal and how much of the instance the "
            "sensor actually recorded. A sensor that never moves is marked flat and drawn on a "
            "padded axis instead of being magnified into noise."
        ),
        (
            "A reading outside the plausible range is drawn in amber over the trace, sample by "
            "sample, so the stretch that is garbage is seen for what it is; the panel's figures "
            "call it out, the header of the block names the sensors, and the feature's checkbox "
            "wears a ⚠."
        ),
        (
            "Two pressures of one line that read <b>out of order</b> (downstream above upstream, "
            "which the flow cannot do) are warned of the same way: the header of the block names "
            "the pair and how often, the samples that contradict each other are drawn dashed in "
            "amber on both plots, whose figures give the share and the largest gap, and both "
            "checkboxes wear a ⚠. The Data availability tab of the help says which pairs are "
            "compared and why."
        ),
        (
            "Every trace draws its <b>measurements as dots</b>, with the line through every sample "
            "faint beneath them: between two dots that line is exactly the straight line the "
            "historian drew, so dense dots are a sensor read every second and sparse dots on a "
            "faint line a sensor read every two minutes and filled in between. The panel's "
            "figures say the share measured and the interval. A valve state is not tested and "
            "keeps its plain line; so does a sensor measured at every sample. Untick "
            "<b>'Measurement dots'</b>, in the Views row, for the plain line throughout, which is "
            "what the file holds and what a pipeline reads; the figures go on saying how much of "
            "it was measured."
        ),
    ],
    "Signal views": [
        (
            "The 'Views' boxes of the instance window add, to every feature plot, two more "
            "views of the same signal, each placed where it shares an axis with the trace. "
            "<b>Distribution</b> is a histogram turned on its side to the right of the trace, on "
            "the trace's value axis, its bars stacked by label period in the class colors, so "
            "that how the event moves the readings is seen inside one instance; a bimodal shape "
            "is an oscillation. A solid line marks the mean and a dashed one the median. "
            "<b>Spectrum</b> takes a row under the trace, the period along the bottom; whenever "
            "it is on, one cycle of its dominant period is laid as a bar against the trace, so "
            "the claim can be checked against the waves."
        ),
        (
            "Both are counted over the stretch of time on screen, so zooming the trace is "
            "brushing: narrow the view to a stretch and read its distribution and its spectrum. "
            "A merged recording is transformed as the single series it is, never stitched from "
            "its parts."
        ),
        (
            "The spectral axis is the <b>period</b>, logarithmic, from two seconds up to the "
            "length of the stretch, and not a frequency: the events are slow (severe slugging on "
            "WELL-00014 cycles every 50 to 90 minutes, flow instability on WELL-00001 every 45), "
            "which in hertz reads 0.0002 and says nothing. The spectrum is Welch's estimate of "
            "the power spectral density, the mean and the linear trend removed first (a trend "
            "would otherwise own every long period), the missing samples interpolated (the grid "
            "is a fixed 1 Hz and the holes are rare), readings outside the plausible range left "
            "out. A frozen sensor, or a stretch with fewer than half its readings, gets a note "
            "instead."
        ),
        (
            "'Segment' sets the length of the segments the spectrum averages over, once 'whole "
            "stretch' is unticked; 'Overlap' how much each repeats of the last; 'Window' the "
            "taper. Nothing longer than a segment can be resolved, and the plots grey the "
            "periods beyond it rather than leave them silently empty. With 'whole stretch' "
            "ticked the spectrum is the periodogram of everything on screen, which is the only "
            "way to see the slugging line: a segment of five minutes, the size a pipeline "
            "windows by, holds no cycle of it. 'Bins' is the number of bins of the histograms."
        ),
        (
            "<b>'Plausible only'</b>, beside 'Bins', is what every histogram counts by default: "
            "the readings inside the plausible range. It is what a histogram is normally asked "
            "for (one gauge reporting 1e12 Pa would otherwise put every genuine reading into the "
            "first bin), but it hides the very thing a data review is looking for, so unticking "
            "it counts the garbage too, on an amber ground beyond the range, with the caption "
            "saying how many were counted rather than how many were left out. The same tick "
            "serves the marginal of an instance window, the Distribution domain of the faults "
            "page and the features page. Spectra are not affected: interpolating over a spike of "
            "1e12 gives the spectrum of the spike, not of the signal, so they always mask it."
        ),
        (
            "The caption of a spectrum gives its <b>dominant period</b> and the share of the power "
            "in it: a few percent for a normal instance, whose power is spread thin, half or more "
            "for an oscillating one. The period is looked for among those the stretch holds at "
            "least four cycles of, so a trend is not mistaken for a line."
        ),
        (
            "On the Faults page the 'Domain' box draws every instance of the fault in one of the "
            "three domains (time series, distribution, spectrum), in either layout, over the "
            "stretch the hours before and after the onset select, so '2 h after' gives the "
            "spectrum of the fault alone. Overlaid spectra read together where overlaid traces "
            "did not, since the question is whether their peaks line up. Histograms are drawn as "
            "a share of each instance's samples, so instances of different length compare: "
            "stacked bars in the grid, a filled area in the series color when overlaid, so that "
            "where two of them sit on top of one another reads as a deeper shade. The mean and "
            "the median of each are lines in the grid, and a triangle over the fullest bin of "
            "each, in either layout, marks the value that instance spends most of its time at, "
            "which the mean and the median both miss once a fault has skewed the readings or "
            "split them in two, and which hovering the curve reads out. 'Normalize per instance' "
            "puts those of different wells on one z-score axis. The second row of the toolbar "
            "holds the hours around the onset, the normalization and the parameters of the "
            "domain chosen; 'Features' and 'Instances' at the right end of the first row hide "
            "the feature panel and the instance list to give the plots its width."
        ),
        (
            "<b>'Overall'</b>, the third entry of 'Layout', is not a third placement but a "
            "reduction before them: the instances of a group are pooled into one curve, which "
            "the overlaid arrangement then draws. On the faults page a group is everything on "
            "show, so each feature gets one curve across every well at once; on the features "
            "page a group is a fault class, so the plot becomes one distribution, or one "
            "spectrum, per class. It is offered off the time axis only: instances cut from "
            "different months have no common clock to be drawn against."
        ),
        (
            "A distribution pools by putting the readings together, a histogram of the union "
            "being a histogram whatever order the samples arrive in. A <b>spectrum does not</b>, "
            "and is never taken over the concatenation: a transform reads consecutive samples as "
            "one second apart, so the months between two instances would become a step and the "
            "seams would spread power across the whole axis. The estimates are averaged band by "
            "band on a shared period axis instead (which is what Welch's method already does "
            "one level down), and a band only the longest instances reach stays theirs alone."
        ),
        (
            "<b>'Join overlapping'</b>, beside it, is what keeps the counts honest. The windows "
            "of a well are cut from one recording, so two that overlap hold the same samples "
            "twice and a pooled histogram would count them twice, inflating it at exactly the "
            "levels that well was recorded twice at. Ticked, those windows are first read as the "
            "single recording they were cut from, by the same rule as everywhere else in the "
            "viewer: every instant once, what one window missed filled in by the one it "
            "overlaps, and windows whose labels disagree there left apart."
        ),
        (
            "Off the time axis nothing is drawn against the hours from the onset, so 'Align at' "
            "reaches a distribution or a spectrum only through the stretch those hours cut around "
            "the anchor. With both hour boxes at 'all' the whole recording is transformed "
            "whichever moment it is aligned on, and the box is greyed to say so; it comes back as "
            "soon as hours around the onset are asked for, or the time series is."
        ),
        (
            "There is no phase spectrum of a single signal: the phase of a transform at a period "
            "is the instant inside the record at which that cycle peaks, so it depends on where "
            "the file happens to begin and tells nothing the trace does not. The phase "
            "<i>difference</i> between two sensors over the same stretch is meaningful, and is "
            "left for a later version."
        ),
        (
            "<b>'Measurements only'</b>, beside 'Plausible only', counts and transforms the "
            "measurements alone, leaving out the samples the historian filled in between them. A "
            "histogram then counts what was read, its caption saying so; a spectrum becomes the "
            "<b>Lomb-Scargle periodogram</b> of the readings at their own instants, which fits a "
            "sinusoid of each period to them by least squares and needs no grid: the honest "
            "spectrum of a series read every ten seconds or every two minutes, where a transform "
            "of the 1 Hz grid is a transform of the historian's lines. Its caption gives the "
            "share of the variance a sinusoid of the peak period explains, and how many "
            "measurements it was taken over; the periods run from twice the typical interval "
            "between measurements up to the stretch. It is scaled so that it integrates to the "
            "variance of the measurements, as a density does, so it sits on the axis Welch's "
            "estimate would and pools with it band by band. The same tick serves the instance "
            "window, the Faults page and the Features page."
        ),
    ],
    "Instances map": [
        (
            "Every point is one real instance, or one bar of the joined view. Hover it to name it "
            "and read its cluster, its typicality and the one-class verdict in the status bar; "
            "click it to open its time series. Drag to pan, Ctrl + wheel to zoom, Ctrl+R to see "
            "every point again."
        ),
        (
            "'Representation' chooses what places the points (the descriptors of the sensors, the "
            "same less the levels, or the DTW distance of one sensor within one class), 'on' "
            "whether the descriptors were taken over the whole 1 Hz grid ('Interpolated') or over "
            "the measurements alone, "
            "'Embedding' how the points are laid on the plane, 'Color by' what colors them. "
            "'Clustering' and 'k' group them, and the line beside scores the grouping: the "
            "silhouette, and the agreement with the fault classes and with the wells."
        ),
        (
            "The list on the right is the label audit: class by class, the instances whose label "
            "disagrees with the one-class model of the normal instances: fault instances that "
            "look normal, normal instances that look anomalous. Hover one to find its point, click "
            "it to open it. Drag its left edge to widen or narrow it; 'Label audit', at the right "
            "of the second row, hides it to give the map its width. It hides itself under the DTW "
            "representation, which compares the instances of one class, and comes back as it was "
            "on leaving it."
        ),
        (
            "What the map computes travels: 'Bar color' on the Timelines can take the cluster or "
            "the typicality of every bar, and 'Sort' above the instance lists of the Faults and "
            "Features pages can order them by typicality or by the one-class score, the figures "
            "appearing in the tooltip of every instance. The first time the page is shown it "
            "reads every instance in full, behind a progress dialog, and keeps the result in the "
            "cache, the same pass the 'Measured vs filled' split uses."
        ),
        (
            "The descriptors themselves travel too: 'Sort' also orders the instance lists of the "
            "Faults and Features pages by the autocorrelation time, the signal-to-noise ratio, "
            "the Gaussianity slope, the skewness or the kurtosis of the feature on show (on the "
            "Faults page, the first feature ticked), largest first, with an 'on' box choosing the "
            "grid or the measurements; the tooltip of every instance then carries both values, "
            "and the caveat that the historian's lines inflate the first two on the grid. On the "
            "Timelines, 'Bar color: Descriptor of a sensor' tints every bar by the same figures."
        ),
        (
            "A control whose optional group is not installed is greyed, and its tooltip names "
            "the group and the command that installs it: 'analysis' for t-SNE, the clusterings, "
            "their scores and the one-class model, 'umap' for UMAP, 'dtw' for the DTW "
            "representation."
        ),
    ],
    "Dispersions page": [
        (
            "Pick two sensors in 'X' and 'Y' and a scope in 'Over': every sample of the "
            "instances of the scope is one dot, the density of the samples shaded behind. The "
            "first look at a scope reads its instances behind a progress dialog and keeps a "
            "subsample for the session; everything else is instant."
        ),
        (
            "Hover a dot for its instance, its instant, its label period and its two readings, "
            "and whether each was measured or filled in by the historian; every other dot of that "
            "instance is brought forward and the rest of the cloud fades, so one recording's "
            "trajectory through the plane can be followed, and the status bar counts the dots of "
            "it on show and the samples in the density cell under the pointer. Click a dot to "
            "open its instance on the two sensors of the plot, X and Y alone, so that the relation "
            "read in the plane can be followed in time. Drag to pan, Ctrl + wheel to zoom, Ctrl+R "
            "to see the whole cloud."
        ),
        (
            "'Color by' colors the dots by fault class, by well or by label period, or shows the "
            "density alone; the key at the right of the second bar names the colors. 'Label "
            "periods' switches the samples of normal operation, the transient, the steady state "
            "and the unlabeled on and off."
        ),
        (
            "'Measurements only' keeps the samples at which both sensors were actually read, "
            "which is where the historian's straight trajectories vanish. 'Join overlapping "
            "instances' reads the joined bars. The caption gives the counts and the Pearson "
            "coefficient over the samples on show."
        ),
    ],
    "Windows page": [
        (
            "Pick a well and a sensor: the first look reads that sensor from every instance of "
            "the well behind a progress dialog and keeps it for the session, then cuts it into "
            "windows of the 'Size' chosen, one label each. 'Instance' keeps one instance's "
            "windows; 'Fault', 'Label' and the ticks filter them."
        ),
        (
            "Click a row, a thumbnail, a window of the strip or a point of a feature to draw the "
            "window large at the bottom, with its label, beside the instance it was cut from "
            "(the window a band with a labeled marker, its stretch of the trace drawn full over "
            "the rest of the instance, faded; the instance shaded by label). Hover the strip for a window's "
            "instance, start and label. Double-click a row, or 'Open instance', to open its "
            "instance in an instance window on this sensor. Ctrl + wheel zooms the plots below "
            "and the strip; Ctrl+R shows them whole."
        ),
        (
            "'View' swaps the thumbnails for one statistic of every window, those of the "
            "statistics table and of the Timelines' descriptor coloring: a point per window "
            "along the well, colored by label period, its distribution per period and the "
            "separation of normal from event windows. The table gains the statistic's column "
            "and the window selected draws it over the signal, a line for a level, a band of one "
            "standard deviation around the mean for the spread. The first statistic asked of a "
            "cut describes every window behind a progress dialog (one to three seconds on the "
            "largest well); the others are then instant."
        ),
    ],
    "3W Toolkit": [
        (
            "<b>'Export file list…'</b>, in the main toolbar, writes the instances the current page "
            "has on show (the wells filtered on the Timelines, the rows of the Availability page, "
            "the instances ticked on the Faults and Features pages, the points of the Instances "
            "map, a joined bar as its instances) as the JSON of a Toolkit "
            '<code>ParquetDatasetConfig</code> with <code>split="list"</code>, each file a path '
            "relative to the dataset root. It loads with "
            "<code>ParquetDatasetConfig(**json.load(open(path)))</code>; its provenance (the "
            "dataset, the page and the choice it was taken from, when) is written beside it as "
            "<code>&lt;name&gt;.provenance.json</code>. <code>scripts/export_file_list.py</code> "
            "writes the same from the command line, by fault class and well, and "
            "<code>examples/</code> holds one it produced, with its provenance."
        ),
        (
            "'Toolkit's CleanSignals', on the Availability page, and 'Bar color: Sensors the "
            "Toolkit's CleanSignals keeps', on the Timelines, apply the Toolkit's cleaning rule to "
            "the instances on show; see <i>Data availability</i>."
        ),
        (
            "Nothing comes back the other way. The Toolkit's <code>ModelAssessment</code> exports "
            "<code>predictions_&lt;timestamp&gt;.csv</code> with the columns "
            "<code>true_values</code>, <code>predictions</code>, <code>model_name</code>, "
            "<code>task_type</code> and <code>timestamp</code>: one row per window the model "
            "scored, in the order the windows were fed, with no instance and no instant in it. "
            "Nothing in that file says which file, let alone which second, a prediction belongs "
            "to, so it cannot be drawn onto the data. What such an export would have to carry is "
            "what the viewer's own model-output format asks for: the instance's file, and the "
            "timestamp of every label."
        ),
    ],
    "Model outputs": [
        (
            "'Load model outputs…', in the main toolbar, opens a folder holding model.json and one "
            "<class>/<instance>.parquet per instance scored (see the <i>Model outputs</i> tab for "
            "the format). The status bar then says how many of the catalogue's instances the model "
            "scored."
        ),
        (
            "Once loaded: a 'model' band under the class band of every instance window, plain "
            "where the verdict agrees with the label and amber where it disagrees; 'Bar color: "
            "Agreement with the model outputs' on the Timelines; 'Color by: Model agreement' on "
            "the Instances map; 'Sort: Agreement with the model outputs' and 'Shade by: Model "
            "outputs' on the Faults and Features pages, whose tooltips carry the figure."
        ),
        (
            "examples/model_outputs holds one set, a PCA control chart over four wells, with its "
            "provenance in its model.json; scripts/pca_control_chart.py produced it and can score "
            "any choice of wells and faults the same way."
        ),
    ],
    "Everywhere": [
        "Drag a plot to pan it. Ctrl with the mouse wheel zooms; the wheel alone scrolls the page.",
        "Ctrl+R resets the views of the window, F1 opens this help.",
        (
            "The Theme box of the main toolbar switches the windows and the plots inside them "
            "together, so the two never disagree; System follows the desktop. The dark mode lifts "
            "the fault hues and shades toward its own dark ground, so the ladder of tints keeps "
            "meaning the same thing. The choice is remembered."
        ),
        (
            "Right-click a plot for pyqtgraph's own menu, which can export the plot as an image or "
            "as data."
        ),
    ],
}
