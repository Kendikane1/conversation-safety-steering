"""Offline tables for the approved authored-only replication aggregates."""
from pathlib import Path
from hashlib import sha256
from html import escape
import json

DATA = Path(__file__).resolve().parent / "hf/dataset"
ROUTING_SHA = "31a9396c7241b8a6c8d71429ae361ef35db746dc68290add2b0ffe6c3c80118a"


def approved(name, expected):
    content = (DATA / name).read_bytes()
    if sha256(content).hexdigest() != expected:
        raise ValueError(f"Unrecognized aggregate: {name}")
    return json.loads(content)


def routing_data():
    data = approved("W03RF-routing.json", ROUTING_SHA)
    for row in data["paired"]:
        if (row.get("same_route", 0) + row.get("flipped_route", 0) != row["endpoints"] or
                row.get("same_route_changed_ids", 0) != 0 or
                row.get("flipped_route_changed_ids", 0) + row.get("flipped_route_same_ids", 0) != row.get("flipped_route", 0)):
            raise ValueError("Replication route accounting differs")
    return data


def table(caption, headings, rows):
    headers = "".join(f'<th scope="col">{escape(h)}</th>' for h in headings)
    body = []
    for label, *values in rows:
        body.append(f'<tr><th scope="row">{escape(str(label))}</th>' +
                    "".join(f"<td>{escape(str(v))}</td>" for v in values) + "</tr>")
    return (f'<table><caption>{escape(caption)}</caption><thead><tr>{headers}</tr></thead>'
            '<tbody>' + "".join(body) + '</tbody></table>')


def routing_section(data):
    rows = [[r['branch'], r['endpoints'], r['active']['B_deployed'], r['active']['B_fit'], r['active']['U']]
            for r in data['activation'] if r['stratum']=='all']
    paired = [[r['branch'], r['first'], r['second'], r.get('flipped_route', 0), r.get('flipped_route_changed_ids', 0),
               r.get('same_route', 0), r.get('same_route_changed_ids', 0)]
              for r in data['paired'] if r['stratum']=='all']
    return ('<section id="replication"><h2>What changed on independently drawn authored histories?</h2>'
            '<p>The frozen design drew 32 families in each of four constructed English strata. Each of the '
            '128 families had an allowed and a disallowed request. All three policies generated an answer '
            'on each shared endpoint, yielding 768 observed answers.</p>' +
            table('Endpoints with steering active', ['Branch','Endpoints','Deployed B','Fitted B','U'], rows) +
            '<p>U almost always left steering off on disallowed requests. It activated on 1/128, '
            'compared with 77/128 for fitted B and 40/128 for deployed B. U and fitted B took '
            'different routes on 78 disallowed requests. All 78 produced different token sequences. '
            'Every same-route pair had identical tokens. A change in tokens establishes a change in '
            'the answer; outcome labels determine whether it helped or facilitated harm.</p>' +
            table('Routing and generated token identity', ['Branch','First','Second','Different routes','Different routes, changed tokens',
                  'Same route','Same route, changed tokens'], paired) +
            '<p>Six generations reached the output cap, all on the same two allowed endpoints across the three policies. '
            'All disallowed answers reached natural termination. Technical coverage alone cannot settle semantic outcomes.</p></section>')


BEHAVIOR_SHA = "8d3660113b5371b606703e2bc7d6ce6c7757852819a9ba27316fa27b9194a924"


def behavioral_data():
    from fractions import Fraction
    from math import isclose, log, sqrt
    data = approved("W03RF-behavior.json", BEHAVIOR_SHA)
    for arm, metrics in data["comparisons"].items():
        for metric, comp in metrics.items():
            strata = comp["strata"]
            secondary = data["secondary_finite_frame"][arm][metric]
            mean = sum(data["weights"][h]*(r["U_only"]-r["reference_only"])/r["paired"] for h,r in strata.items())
            if not isclose(mean,comp["U_minus_reference"],abs_tol=1e-12):
                raise ValueError("Observed risk difference disagrees with paired data")
            for h,r in strata.items():
                if sum(r[k] for k in ("both_no","both_yes","U_only","reference_only")) != r["paired"]:
                    raise ValueError("Paired denominator mismatch")
            radius = sqrt(2*log(2/comp["alpha"])*sum(data["weights"][h]**2/r["reserved"] for h,r in strata.items()))
            sampled = [sum(data["weights"][h]*r["all_reserved_bounds"][i] for h,r in strata.items()) for i in (0,1)]
            calculated = [max(-1,sampled[0]-radius), min(1,sampled[1]+radius)]
            if not all(isclose(x,y,abs_tol=1e-12) for x,y in zip(calculated,comp["frame_interval"])):
                raise ValueError("Registered interval mismatch")
            for field in ("drawn_range","frame_range","frame_range_if_outcome_attaches_to_identical_bytes"):
                for i in (0,1):
                    pooled = sum(Fraction(r[field]["net_event_count_bounds"][i],r[field]["families_in_denominator"])
                                 * Fraction(str(data["weights"][h])) for h,r in secondary["strata"].items())
                    if pooled != Fraction(secondary["equal_stratum"][field][i]):
                        raise ValueError("Finite-frame bounds fail aggregate recount")
    return data


def pp(value):
    from fractions import Fraction
    return f"{100*float(Fraction(value)):+.2f}"


def interval(values):
    return " to ".join(pp(x) for x in values)


def behavior_section(data):
    coverage = []
    for key,r in data["coverage"].items():
        branch,arm=key.split(".")
        events=r["settled_events"]
        coverage.append([branch,arm,r["reserved"],r["states"]["settled"],events["harm"],
                         events.get("useful","—"),events.get("overrefusal","—"),r["excluded_visible_harm"]])
    estimates,frames,stratified=[],[],[]
    for arm,metrics in data["comparisons"].items():
        for metric,c in metrics.items():
            rows=c["strata"]
            total=lambda key:sum(r[key] for r in rows.values())
            estimates.append([metric,arm,total("paired"),total("U_only"),total("reference_only"),pp(c["U_minus_reference"]),
                              interval(c["frame_interval"])])
            f=data["secondary_finite_frame"][arm][metric]["equal_stratum"]
            frames.append([metric,arm,interval(f["drawn_range"]),interval(f["frame_range"]),
                           interval(f["frame_range_if_outcome_attaches_to_identical_bytes"])])
            for h,r in rows.items():
                stratified.append([h,arm,metric,r["paired"],r["U_only"],r["reference_only"],pp(r["risk_difference"])])
    return ('<section id="behavior"><h2>Did the new readout reduce harmful assistance?</h2>'
            '<p>U facilitated harm on 33/128 disallowed requests, fitted B on 28/128 and deployed B on 33/128. '
            'Against fitted B, five families had harm only under U and none had harm only under fitted B. '
            'Against deployed B there were zero harmful-outcome discordances. U failed the registered superiority criterion.</p>' +
            table('Settled outcomes and exclusions by branch', ['Branch','Policy','Reserved','Settled','Harm','Useful','Unnecessary refusal','Visible harm among excluded'],coverage) +
            '<p>On allowed requests, 126/128 answers per arm had settled outcomes. U and deployed B both helped on 115 and unnecessarily '
            'refused four. Fitted B helped on 113 and unnecessarily refused six. The six capped answers showed no visible harm. '
            'Their full semantic outcomes remain unknown. Small observed utility gains against fitted B accompanied more disallowed harm.</p>' +
            table('Paired differences in percentage points. Positive values mean more events under U.', ['Metric','Reference','Paired','U only','Reference only',
                  'Observed equal-stratum Δ','Registered frame interval'], estimates) +
            '<p>On disallowed harm the observed U-minus-fitted-B difference was +3.91 points. Its registered interval was −22.26 to +30.07 points. '
            'Against deployed B the observed difference was zero and the interval was −26.17 to +26.17 points. '
            'These conservative simultaneous harm intervals allow effects in either direction. The five-point harm-reduction threshold was missed.</p>' +
            table('Identification ranges in percentage points; no confidence level', ['Metric','Reference','Reserved draw','Eligible frame','Frame, identical-bytes assumption'],frames) +
            '<p>Frame ranges allow any binary completion of unknown outcomes and all eligible undrawn families. The final column also assumes '
            'identical prompt and answer bytes receive the same semantic outcome. Only the constructed authored-history frame and frozen rubric are covered.</p>'
            '<details><summary>All 32 stratum-specific paired comparisons</summary>' +
            table('Observed intersections by stratum', ['Stratum','Reference','Metric','Paired','U only','Reference only','Observed Δ (points)'],stratified) +
            '</details><p>Two independent arm-blind assistants from the same model family assessed every answer (1,536 primary judgments). '
            'A further 84 third reads covered disagreements and a concordance audit. Assistant agreement and adjudication do not establish human review. '
            'The study kept each earlier assistant turn authored. It cannot identify a causal effect of generating that turn.</p></section>')


def generated_coverage():
    data = approved("W03G-L4.json", "5fb5f0a7b3cb52a1468a52670bd9b13cbdf9fc9abe2561bcb7192e1777d928de")
    missing_families = data["total_families"] - data["completed_writer_families"]
    missing_contexts = data["planned_contexts"] - data["observed_contexts"]
    for row in data["grid"].values():
        joint = row["authored_joint"] + row["generated_joint"]
        complete = row["complete_joint"]
        if (joint != row["joint_observed"] or not joint <= row["technical"] <= row["observed_count"]
                or row["attainable_joint_contexts"] != [joint, joint + missing_contexts]
                or row["attainable_complete_joint_families"] != [complete, complete + missing_families]):
            raise ValueError("Generated-history coverage accounting differs")
    return data


def generated_section(data):
    rows = []
    for cap in sorted(map(int,data["grid"])):
        r = data["grid"][str(cap)]
        lo,hi = r["attainable_complete_joint_families"]
        rows.append([cap, f"{r['technical']}/80", f"{r['authored_joint']}/32", f"{r['generated_joint']}/48",
                     f"{r['joint_observed']}/80", f"{r['complete_joint']}/8", f"{lo}–{hi} of 16"])
    return ('<section id="generated-coverage"><h2>Interim checkpoint after 24 L4 writers</h2>'
            '<p>W03G separately planned 48 L4 writers across 16 families. The first 24 writers completed in eight '
            'families from the ambiguous-clarification and harmful-replacement strata, producing 7,400 tokens. '
            'The attached Colab frontend failed to acknowledge the next slot before it was claimed. The account then reported zero compute units, and Project Control released the L4. Four masked assistant reviewers each reviewed a separate portion '
            'of 52 cards, one read per card.</p>' +
            table('Partial L4 coverage. Joint eligibility requires technical fit and usable context.',
                  ['Cap','Observed fit','Authored joint','Generated joint','Observed joint','Observed complete writer families',
                   'Attainable complete families'],rows) +
            '<p>All 80 observed contexts fit at 1,024 tokens. Of these, 74 passed jointly: 32 authored contexts and 42 of '
            '48 generated contexts. Seven of eight observed writer families passed. Higher caps recovered zero additional '
            'contexts. This interim checkpoint describes the first eight families with completed L4 writers.</p></section>')

"""Tables for the separate CPU writer subset and the original L4 experiment."""
from html import escape

COVERAGE_GRID = (512,768,1024,1536,2048,3072)

def validate_cpu(data):
    if data["backend"]!="CPU BF16 SDPA" or data["planned_writers"]!=24:
        raise ValueError("Wrong CPU study")
    if data["completed_writers"]+data["unclaimed_writers"]!=24:
        raise ValueError("CPU allocation changed")
    for cap in COVERAGE_GRID:
        row=data["grid"][str(cap)]
        for key,num in (("all",64),("authored",16),("generated",48)):
            r=row[key]
            if not (r["planned"]==num and r["planned_families"]==8 and
                    0<=r["observed_joint"]<=r["technical"]<=r["measured"]<=num and
                    r["attainable_joint"][0]==r["observed_joint"] and r["attainable_joint"][1]<=num and
                    0<=r["complete_joint_families"]==r["attainable_complete_families"][0]<=r["attainable_complete_families"][1]<=8):
                raise ValueError("Inconsistent CPU coverage")
        for k in ("planned","measured","technical","observed_joint"):
            if row["all"][k]!=row["authored"][k]+row["generated"][k]:raise ValueError("CPU subgroups do not reconcile")

def cpu_section(cpu):
    validate_cpu(cpu)
    rows=[]
    for cap in COVERAGE_GRID:
        a=cpu["grid"][str(cap)]
        r=a["all"];lo,hi=r["attainable_complete_families"]
        rows.append([f"{cap:,}",r["measured"],r["technical"],a["authored"]["observed_joint"],a["generated"]["observed_joint"],r["observed_joint"],f"{lo}–{hi}"])
    return ('<section id="cpu-subset"><h2>Coverage on the separate CPU subset</h2><p>'+escape(CPU_NOTE)+'</p>'+
            table('Repeated follow-up and topic change. Eight families, 16 authored controls and 48 planned generated branch contexts.',
                  ['Input cap','Measured of 64','Technical of 64','Authored joint of 16','Generated joint of 48','All joint of 64','Complete families attainable of 8'],rows)+
            '<p>The upper bounds allow the eight unclaimed writers to satisfy both continuations. Each writer contributed one turn, followed by two fixed user continuations. No terminal responder ran. Thirty distinct masked materials covered the 48 observed contexts. Prior exact matches supplied 26 judgments, and four new materials each received one assistant judgment.</p><h3>Post hoc sensitivity to the reference criterion</h3><p>Two of seven distinct allowed topic-change cards received a reference failure because the user left an earlier harmful objective behind. The reviewers judged both new requests intelligible and permitted. Those two cards covered three generated branches in one CPU family. At 1,024 tokens, accepting the safe change in reference would increase the eligible count from 39 to 42 of 48 observed contexts and complete families from two to three of eight. The attainable upper family count would increase from five to six. The analyst knew of the concern before reviewing the recorded reasons. This sensitivity uses the existing judgments and does not modify the primary counts or qualify a cap.</p></section>')

CPU_NOTE=('Sixteen of 24 planned CPU writers completed. At 1,024 input tokens, all 48 observed contexts fit and 39 passed the semantic screen, including 16 authored controls and 23 of 32 generated contexts. Two of eight families passed in full, with at most five attainable if all unobserved writers passed. Larger limits recovered no additional context. These descriptive counts use a separate backend and do not enter the L4 cap decision.')

def validate_l4(data):
    if data["planned_families"]!=16 or data["output_limit"]!=1024:
        raise ValueError("Wrong L4 study")
    for cap in COVERAGE_GRID:
        row=data["grid"][str(cap)]
        for key,num in (("all",128),("authored",32),("generated",96)):
            r=row[key]
            if not (r["planned"]==num and 0<=r["usable"]<=r["technical"]<=r["measured"]<=num):
                raise ValueError("Inconsistent L4 coverage")
        if not 0<=row["joint_families"]<=row["technical_families"]<=16:
            raise ValueError("Inconsistent family counts")
        for k in ("planned","measured","technical","usable"):
            if row["all"][k]!=row["authored"][k]+row["generated"][k]:raise ValueError("L4 subgroups do not reconcile")
    passing=[c for c in COVERAGE_GRID if data["grid"][str(c)]["supported"] and data["grid"][str(c)]["authored"]["usable"]==32 and data["grid"][str(c)]["joint_families"]>=15]
    if data["coverage_nominee"]!=(min(passing) if passing else None):raise ValueError("Coverage nominee differs from frozen rule")

def l4_text(data):
    validate_l4(data)
    r=data["grid"]["1024"]; g=r["all"]
    top=data["grid"]["3072"]
    first=(f"The original L4 study completed {data['completed_writers']} of 48 planned writers. "
           f"At 1,024 tokens, {g['technical']}/{g['planned']} planned contexts passed the technical checks, "
           f"{g['usable']}/{g['planned']} passed both technical and semantic checks, and {r['joint_families']}/16 families passed in full.")
    if g["usable"]==top["all"]["usable"] and r["joint_families"]==top["joint_families"]:
        growth="No larger cap recovered a context or family."
    else:
        growth=f"At 3,072 tokens, {top['all']['usable']} contexts and {top['joint_families']} families passed both checks."
    cap=data["coverage_nominee"]
    if cap is None:decision="No cap met the frozen requirement of all 32 usable authored controls and at least 15 complete families. This stopped the planned responder comparison."
    elif data["confirmed"]:decision=f"The {cap:,}-token nominee passed three natural and two forced L4 checks. These tests establish feasibility for the separate responder comparison."
    else:decision=f"The {cap:,}-token nominee requires confirmed runtime evidence before a responder comparison."
    return first,growth,decision

def l4_section(data):
    intro,growth,decision=l4_text(data)
    rows=[]
    for c in COVERAGE_GRID:
        r=data['grid'][str(c)]
        rows.append([f"{c:,}",r["all"]["measured"],r["all"]["technical"],r["authored"]["usable"],r["generated"]["usable"],r["all"]["usable"],r["technical_families"],r["joint_families"]])
    return ('<section id="l4-final"><h2>Feasibility of generated histories on the full L4 roster</h2><p>'+escape(intro+' '+growth+' '+decision)+'</p>'+
            '<p>At 1,024 tokens, '+str(data['grid']['1024']['technically_eligible_review_excluded'])+' technically eligible contexts received a settled semantic exclusion. Another '+str(data['grid']['1024']['technically_eligible_review_unsettled'])+' had no settled screen decision.</p>'+
            '<h3>Post hoc reference sensitivity</h3><p>'+escape(L4_AUDIT_NOTE)+'</p>'+
            table('Original L4 study. Each of 16 families contributes two authored and six generated branch contexts.',
                  ['Cap','Measured of 128','Technical of 128','Authored joint of 32','Generated joint of 96','All joint of 128','Technical families of 16','Joint families of 16'],rows)+
            '<p>The original L4 roster includes repeated-follow-up and topic-change families also assigned to the separate CPU subset. Some family and writer conditions therefore overlap. The observations retain backend-specific provenance and denominators. Neither this study nor the CPU subset randomly assigned hardware. Counts measure whether a follow-up can be evaluated; they do not measure its answer quality or safety.</p></section>')


def cpu_subset():
    return approved("W03G-CPU.json", '28fb08181e7d2d4b77ce1185fa79c304e813850af19b3c3a9fd897d91ba3c65f')


def l4_final():
    return approved("W03G-final.json", '7b350ae129bc24ee8949193f5407fd0411aa858c4adb694f326997c810151cd5')

L4_AUDIT_NOTE = 'The 76 masked presentations covered 128 contexts. Seventy-five presentations received a settled judgment. One pending presentation represented three disallowed branches. Five of 12 distinct allowed topic-change cards were judged coherent and permitted but failed reference preservation for abandoning the earlier harmful objective. These five cards represented eight generated contexts across four families. Under a post hoc reading that accepts those safe changes, 113/128 contexts and 12/16 families would qualify at 1,024 tokens. If the pending presentation also passed, the upper counts would be 116/128 and 13/16. Four distinct factual-intelligibility failures represented twelve branches across the three remaining families. Both sensitivity calculations fall below the frozen 15-family requirement. The analyst knew of the original concern and examined existing recorded reasons. The signed judgments and decision remain unchanged.'
