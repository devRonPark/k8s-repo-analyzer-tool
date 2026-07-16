"""Build-system detection and selection (pure).

A repository can ship more than one build system (spring-petclinic carries both
``pom.xml`` and ``build.gradle``). This module never "picks the first pom.xml it
finds": it enumerates every build system present, records which one was selected
and why, and states how to select the other. Selection is deterministic and can
be forced with ``--build-system {auto,gradle,maven}``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..models import AnalysisResult, Evidence, Finding, Warning
from ..parsers.gradle import GradleBuild
from ..parsers.maven import MavenProject

# Deterministic tie-break order when the request is ``auto`` and the repository
# contains more than one build system that is otherwise equally plausible.
_AUTO_PRIORITY = ("gradle", "maven")
_VALID_REQUESTS = {"auto", "gradle", "maven"}


@dataclass
class BuildSystemSelection:
    detected: list[str]
    selected: str
    rationale: str
    override_hint: str
    evidence: list[Evidence] = field(default_factory=list)
    ambiguous: bool = False


def _primary_gradle(gradles: dict[str, GradleBuild]) -> tuple[str, GradleBuild] | None:
    if not gradles:
        return None
    path = sorted(gradles, key=lambda p: (p.count("/"), p))[0]
    return path, gradles[path]


def _primary_maven(mavens: dict[str, MavenProject]) -> tuple[str, MavenProject] | None:
    if not mavens:
        return None
    path = sorted(mavens, key=lambda p: (p.count("/"), p))[0]
    return path, mavens[path]


def _gradle_is_spring_boot(gradle: GradleBuild) -> bool:
    return gradle.plugin_prefixed("org.springframework.boot") is not None


def _maven_is_spring_boot(maven: MavenProject) -> bool:
    if maven.has_dependency("org.springframework.boot"):
        return True
    return any(p.artifact_id == "spring-boot-maven-plugin" for p in maven.build_plugins)


def resolve_build_system(
    *,
    requested: str,
    gradles: dict[str, GradleBuild],
    mavens: dict[str, MavenProject],
) -> tuple[BuildSystemSelection | None, list[Warning]]:
    """Decide which build system to analyze. Returns ``(selection, warnings)``;
    ``selection`` is ``None`` when the repository has no Java build system."""

    warnings: list[Warning] = []
    requested = requested if requested in _VALID_REQUESTS else "auto"

    gradle_primary = _primary_gradle(gradles)
    maven_primary = _primary_maven(mavens)
    detected: list[str] = []
    if gradle_primary is not None:
        detected.append("gradle")
    if maven_primary is not None:
        detected.append("maven")
    if not detected:
        return None, warnings

    evidence: list[Evidence] = []
    if gradle_primary is not None:
        gpath, gbuild = gradle_primary
        boot = gbuild.plugin_prefixed("org.springframework.boot")
        loc = boot.location if boot is not None else None
        evidence.append(
            Evidence(
                path=gpath,
                selector="plugins" if loc is None else "plugins.spring-boot",
                symbol="build.gradle",
                start_line=loc.start_line if loc else 1,
                end_line=loc.end_line if loc else 1,
            )
        )
    if maven_primary is not None:
        mpath, mproject = maven_primary
        span = mproject.packaging_line or (1, 1)
        evidence.append(
            Evidence(path=mpath, selector="project", symbol="pom.xml", start_line=span[0], end_line=span[1])
        )

    # Honour an explicit request when that build system is actually present.
    if requested in detected:
        other = [d for d in detected if d != requested]
        selection = BuildSystemSelection(
            detected=sorted(detected),
            selected=requested,
            rationale=f"explicitly requested via --build-system {requested}",
            override_hint=_override_hint(other),
            evidence=evidence,
            ambiguous=len(detected) > 1,
        )
        if len(detected) > 1:
            warnings.append(_multi_warning(detected, requested))
        return selection, warnings

    if requested != "auto":
        # Requested a build system the repo does not contain: fall back to auto.
        warnings.append(
            Warning(
                code="build_system_not_found",
                message=(
                    f"--build-system {requested} was requested but no {requested} build was found; "
                    f"detected: {', '.join(sorted(detected))}. Falling back to automatic selection."
                ),
            )
        )

    if len(detected) == 1:
        selected = detected[0]
        return (
            BuildSystemSelection(
                detected=sorted(detected),
                selected=selected,
                rationale="only build system detected in the repository",
                override_hint="n/a (single build system)",
                evidence=evidence,
                ambiguous=False,
            ),
            warnings,
        )

    # Multiple build systems, no explicit request: choose deterministically and
    # say so loudly. Prefer a Spring Boot build if exactly one qualifies; else a
    # fixed priority order.
    spring_boot = set()
    if gradle_primary is not None and _gradle_is_spring_boot(gradle_primary[1]):
        spring_boot.add("gradle")
    if maven_primary is not None and _maven_is_spring_boot(maven_primary[1]):
        spring_boot.add("maven")

    if len(spring_boot) == 1:
        selected = next(iter(spring_boot))
        rationale = (
            f"both {', '.join(sorted(detected))} builds are present; only the {selected} build is a "
            "Spring Boot application, so it was selected"
        )
    else:
        selected = next(b for b in _AUTO_PRIORITY if b in detected)
        rationale = (
            f"both {', '.join(sorted(detected))} builds are present and equally plausible; selected "
            f"'{selected}' by the deterministic default order {list(_AUTO_PRIORITY)}"
        )
    other = [d for d in detected if d != selected]
    warnings.append(_multi_warning(detected, selected))
    return (
        BuildSystemSelection(
            detected=sorted(detected),
            selected=selected,
            rationale=rationale,
            override_hint=_override_hint(other),
            evidence=evidence,
            ambiguous=True,
        ),
        warnings,
    )


def _override_hint(other: list[str]) -> str:
    if not other:
        return "n/a (single build system)"
    return "; ".join(f"--build-system {name} to analyze the {name} build instead" for name in other)


def _multi_warning(detected: list[str], selected: str) -> Warning:
    return Warning(
        code="multiple_build_systems",
        message=(
            f"multiple build systems detected ({', '.join(sorted(detected))}); analysis uses '{selected}'. "
            f"Override with --build-system {{{','.join(sorted(detected))}}}."
        ),
    )


def emit_build_system_findings(result: AnalysisResult, selection: BuildSystemSelection) -> None:
    result.configuration.append(
        Finding(
            subject="build.system",
            value=selection.selected,
            confidence="derived" if selection.ambiguous else "explicit",
            kubernetes_effect=(
                "determines the build/CI pipeline and the image-build strategy; "
                f"detected build systems: {', '.join(selection.detected)}"
            ),
            evidence=selection.evidence,
        )
    )
    result.configuration.append(
        Finding(
            subject="build.system.selection",
            value={
                "detected": selection.detected,
                "selected": selection.selected,
                "rationale": selection.rationale,
                "how_to_select_other": selection.override_hint,
            },
            confidence="explicit",
            kubernetes_effect="records why this build system was chosen and how to analyze the other(s)",
            evidence=selection.evidence,
        )
    )
