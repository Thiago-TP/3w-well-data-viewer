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
# The valves of ``config.STATE_VALVE_RULES`` by the names the article gives them.
VALVE_NAMES: dict[str, str] = {
    "ESTADO-M1": "M1",
    "ESTADO-W1": "W1",
    "ESTADO-SDV-P": "SDV-P",
    "ABER-CKP": "PCK",
    "ESTADO-PXO": "PXO",
    "ESTADO-XO": "XO",
}
STATE_UNCHECKED = "not checked: no set of valve positions holds through it (see below)"
STATE_VALVE_NOTE = (
    "The article defines each status by the positions of the valves (the <b>Valves</b> of each "
    "row): the production path is the master and wing valves of the tree, the production SDV and "
    "the production choke (M1, W1, SDV-P, PCK), and the crossovers between the service and "
    "production lines are PXO and XO. The instance window checks every labeled stretch against "
    "the valves recorded, both ways round, since valves that move under an unchanged label "
    "contradict it: where they do, either the expert's label or a valve's tag is not to be "
    "believed. A valve not recorded, or in between, decides nothing, and a choke is closed at "
    "0 %. The experts set the label by hand, a little before or after the valves move, so the "
    "5 minutes either side of a change of the label are not compared, and a status counts as "
    "contradicted when its valves contradict it in more than 1 % of the samples compared. The "
    "header of the block names the status and the valves in red, the stretch is hatched over "
    "red on the state band, named by its status and its valves, the valve's own plot hatches "
    "it in see-through red behind the trace, and its checkbox wears a ⚠. On the Availability "
    "page the cell of the valve, and on the Timelines the bar, wear a red triangle in their "
    "top-left corner, once the profile pass has run. A survey of every real instance of 3W 2.0.0 departs from the article "
    "twice: Bullheading, whose rule (every production valve open) fails in all 4 instances that "
    "carry it, in 41 to 100 % of their samples, is not checked, and Depressurization asks one "
    "valve of the tree closed rather than both, which is what isolates the well from the line "
    "being bled. Under these rules 41 of the 1,119 real instances contradict their valves, all "
    "but two labeled Open while a valve of the path reads closed or a crossover open, mostly for "
    "the whole recording: SDV-P on 18 instances of WELL-00004, W1 on all 8 of WELL-00022, PXO on "
    "WELL-00029."
)

# The dataset's own facts, for the help's Notes on the data tab.
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
    (
        "state",
        "Against the well state",
        (
            "The red mark, in the top-left corner, of a valve that contradicts the well status "
            "its experts labeled in at least one instance of the row: Open while a valve of the "
            "production path reads closed or a crossover open, Shut-In while every valve of the "
            "path reads open, and so on, as the 3W 2.0.0 article defines each status (see the "
            "Well status tab). Either the label or the valve's tag is not to be believed. Hover "
            "the cell for how many instances and for the statuses. Known once the profile pass "
            "has run, like the mark of the pressures out of order."
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
            "The viewer shows the measurements in three places. Every time series draws them as "
            "dots, with the line through every sample (which between two dots is exactly the "
            "historian's line) faint beneath: dense dots are a sensor read every second, sparse "
            "dots on a faint line a sensor filled in. <i>Measured vs filled</i>, on this page, "
            "splits the live share of every cell. And <i>Measurements only</i>, in the toolbar of the signal views, counts and "
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
            "the event or the well they came from."
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
            "colors the points (full for the medoid, faint for the farthest), and it is a sort "
            "order of the instance lists of the Faults and "
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
            "page is computed again on the bars; the instance lists of the other pages, which "
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
            "the block gives the agreement. On the <b>Instances map</b>, <i>Color by: Model "
            "agreement</i> tints the points by it, faint for none and full for all, empty where "
            "the model scored nothing. On the <b>Faults</b> and <b>Features</b> pages the instance lists "
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
            "quartiles, maximum, skewness, excess kurtosis) and the descriptors of the "
            "Instances map (autocorrelation time, signal-to-noise ratio, Gaussianity slope), taken by "
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
    "descriptors, the ones the <i>Instances map</i> places its points by."
)
