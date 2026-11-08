# Repository Metadata and Placeholder Central Registry

> **The single registry** (ruling by the lead (主理人) + `docs/ARCHITECTURE-OPENSOURCE.md` v1.1 §5.1; replaces the old registration location in PRD-OPENSOURCE §4.1).
> All deliverable files containing URLs/identities may only reference the symbols in this table; scattering different hardcoded variants is forbidden.
> Repository address not yet in place (no `.git`/no remote, same-name repository 404, the origins of the other 24 sub-repositories in the workspace belong to other projects and must not be borrowed):
> deliver the **placeholder version**; **before pushing, S2 must perform a one-shot full replacement**.
> The Architect/Engineer/QA perform no git operations and do not push (S1–S7 belong to the lead (主理人) #9).

---

## 1. Unified placeholder symbol table (11 symbols · 6 columns)

| Placeholder key | Category | Purpose | Default value (user-replaceable) | Files where it appears (RP points) | Post-replacement verification |
| --- | --- | --- | --- | --- | --- |
| `__REPO_URL__` | Address · to be provided by the user | Full repository URL | `<to be provided by the user; fabrication forbidden>` | RP-01~04, 06, 08, 10, 11 | repo-wide `grep -r "__REPO_URL__"` = 0; the URL is identical at all occurrences; accessible via `curl -I` at stage S6 |
| `__OWNER__` | Address · derived | Repository owner | Parsed from `__REPO_URL__` (**must not be reverse-inferred from the account name**) | RP-04, 06 (as needed) | 0 grep residues; consistent with the owner segment in the URL |
| `__REPO_NAME__` | Address · derived | Repository name (the `cd` directory) | Parsed from `__REPO_URL__` | RP-02, 08 | 0 grep residues; consistent with the final URL segment |
| `__CI_BADGE_URL__` | Address · derived | CI badge image URL | `__REPO_URL__ + /actions/workflows/ci.yml/badge.svg` | RP-01 | 0 grep residues; consistent with the derivation formula |
| `__DEFAULT_BRANCH__` | Address · derived | Branch segment of `blob` paths | `main` | RP-04, 11 | 0 grep residues; consistent with the repository's actual default branch |
| `__AUTHOR_NAME__` | Identity · has a default | Author/copyright holder | `Nephets1010` (gh-verified login account, owner of the target repository) | RP-05, 07, 12 | Value matches the gh account; no real names fabricated |
| `__AUTHOR_EMAIL__` | Identity · has a default | Author/contact email | `Nephets1010@users.noreply.github.com` (default value; **already replaced by the user-confirmed value, see §6 for the actual value**) | RP-05, 07, 09, 10 | Consistent with the actual value in §6; the user is aware it is publicly visible |
| `__COPYRIGHT_YEAR__` | Identity · has a default | Copyright year | `2026` (current year) | RP-12 | Value is the current year |
| `__COPYRIGHT_HOLDER__` | Identity · has a default | Copyright holder | `Nephets1010` | RP-12 | Consistent with `__AUTHOR_NAME__` |
| `__SECURITY_CONTACT__` | Contact · has a default | Security/code-of-conduct reporting channel | `Nephets1010@users.noreply.github.com` (default value; **already replaced by the user-confirmed value, see §6 for the actual value**) | RP-09, 10 | Consistent with the actual value in §6; the user is aware it is publicly visible |
| `__RELEASE_DATE__` | Metadata · to be provided by the user | CHANGELOG/CITATION release date | `<to be provided by the user; month/day must not be fabricated>` | RP-11, CHANGELOG, CITATION | 0 grep residues; format `YYYY-MM-DD` |

**The two iron rules of distinction** (v1.1 §5.1):

1. **Identity-type symbols have verifiable defaults; address-type ones do not**: `Nephets1010` is the gh-verified login account and owner of the target repository, usable for author/copyright; but the repository name is unconfirmed and the same-name repository 404s, so **assembling a repository URL from that account is forbidden**.
2. **Borrowing** the origins of the other 24 sub-repositories in the workspace is forbidden; the sole source of the address = the URL provided by the user.

> In deliverable files, identity fields **still carry the placeholder symbols** (full-placeholder delivery); default values are only registered in this table, annotated as "default value, user-replaceable", and replaced in one shot per this table at S2.

---

## 2. Point-by-point mapping of the 12 RP points

| RP | Location | Referenced symbols | Category |
| --- | --- | --- | --- |
| **RP-01** | `README.md` §8.1 badges (CI badge img/href, License) | `__CI_BADGE_URL__`, `__REPO_URL__` | URL |
| **RP-02** | `README.md` §8.2 clone | `__REPO_URL__`/`__REPO_NAME__` | URL |
| **RP-03** | `README.md` §8.4–8.7 Issues/PR/Homepage | derived from `__REPO_URL__` | URL |
| **RP-04** | `pyproject.toml [project.urls]` 5 sub-keys | `__REPO_URL__` + `__DEFAULT_BRANCH__` + `__OWNER__` | URL |
| **RP-05** | `pyproject.toml authors`/`maintainers` | `__AUTHOR_NAME__`/`__AUTHOR_EMAIL__` | Identity |
| **RP-06** | `CITATION.cff url`/`repository-code` | `__REPO_URL__`/`__OWNER__` | URL |
| **RP-07** | `CITATION.cff authors` | `__AUTHOR_NAME__`/`__AUTHOR_EMAIL__` | Identity |
| **RP-08** | `CONTRIBUTING.md` clone/Issue/PR/CI links | `__REPO_URL__`/`__REPO_NAME__` | URL |
| **RP-09** | `CODE_OF_CONDUCT.md` reporting channel | `__SECURITY_CONTACT__` | Contact |
| **RP-10** | `SECURITY.md` reporting channel/advisories | `__REPO_URL__` or `__SECURITY_CONTACT__` | URL/Contact |
| **RP-11** | `CHANGELOG.md` bottom version-compare link | `__REPO_URL__` + `__DEFAULT_BRANCH__` + `__RELEASE_DATE__` | URL/Metadata |
| **RP-12** | `NOTICE` copyright line | `__COPYRIGHT_YEAR__`/`__COPYRIGHT_HOLDER__` | Identity |

**Statistics**: 12 dependency points = **9 needing a real repository URL/contact channel** (RP-01~04, 06, 08~11, with RP-11 also containing a date) + **3 needing author and copyright identity** (RP-05, 07, 12). All symbols are centralized in `docs/REPO_METADATA.md`.

**Boundary notes on the reference points (for QA verification)**:

- The 12 RP points in the table above are the **only actual reference points**, spread across the 9 open-source/metadata files and `README.md` §8.
- This registry itself, and the symbol names appearing in `docs/PRD-OPENSOURCE.md`/`docs/ARCHITECTURE-OPENSOURCE.md`/`docs/TASKS-OPENSOURCE.md`, are **explanatory text/indexes**, not reference points, and are not counted as S2 replacement targets.
- While the address is not in place, `__...__` residues are allowed repo-wide, but nothing may be pushed; after S2 the **deliverable files** must have 0 residues.

---

## 3. The sole derivation rules and replacement order

```
__CI_BADGE_URL__  := __REPO_URL__ + "/actions/workflows/ci.yml/badge.svg"
__DEFAULT_BRANCH__ := main (replaceable; must match the repository's actual default branch)
__OWNER__ / __REPO_NAME__ := parsed from the user-provided URL; reverse inference forbidden
```

| Purpose | Derived expression |
| --- | --- |
| Issues | `__REPO_URL__/issues` |
| Pull Requests | `__REPO_URL__/pulls` |
| Changelog | `__REPO_URL__/blob/__DEFAULT_BRANCH__/CHANGELOG.md` |
| Documentation | `__REPO_URL__/blob/__DEFAULT_BRANCH__/README.md` |
| Security Advisories | `__REPO_URL__/security/advisories/new` |
| Release tag | `__REPO_URL__/releases/tag/v1.0.0` |
| Version compare | `__REPO_URL__/compare/v1.0.0...__DEFAULT_BRANCH__` |

**S2 replacement order** (avoiding "symbols nested inside symbols" residues): first expand the derived symbols
`__DEFAULT_BRANCH__` / `__CI_BADGE_URL__` / `__OWNER__` / `__REPO_NAME__`
→ then replace `__REPO_URL__` → finally the identity/date symbols → `grep` to confirm 0 residues in deliverable files.

> **Branch verification note**: the branch segment must match the actual value `main` in §6; `blob/main` is a valid final value,
> and old-branch residues are checked only when the user specifies a different branch. The current repository default branch is `main` (see §6),
> so the `blob/main` in the issues/PR/compare links needs no replacement.

---

## 4. Freeze gate and the S1–S7 handoffs

1. **Current status (address not in place)**: deliver the placeholder version; `__...__` residues allowed repo-wide, **pushing forbidden**.
2. **S1**: the user provides a real URL or authorizes using an existing repository (Q-OS2 explicitly states **no new repository is created**); the lead (主理人) confirms owner/repo/visibility.
3. **S2**: replace all 12 RP points in one shot per §1/§2. After replacement, run the command below (**excluding the explanatory text of design documents under `docs/`, checking only actual artifacts**; this registry itself, as a historical index, is not included), expecting **0 residues**; also verify the 12 URLs are fully identical, no fabricated owner/repo, no scattered hardcoding, no old-branch spellings:

   ```bash
   grep -rnE '__[A-Z_]+__' --exclude-dir=data --exclude-dir=__pycache__ \
     --exclude-dir=.pytest_cache --exclude='REPO_METADATA.md' \
     README.md pyproject.toml CITATION.cff CONTRIBUTING.md CODE_OF_CONDUCT.md \
     SECURITY.md CHANGELOG.md NOTICE LICENSE .github/workflows/ci.yml
   # After S2, expect: no output (0 residues); the branch segment must match the actual value main in §6,
   # blob/main is a valid final value; old-branch residues are checked only when the user specifies a different branch
   ```
4. **S3**: final local verification (PRD-OPENSOURCE §3 ten criteria + ARCH-OPENSOURCE v1.1 §7 A–F).
5. **S4**: `git init` → remote (**only the user-provided address**) → first local commit [**stop before pushing**]; the commit message contains no secrets.
6. **S5**: push after user authorization → **S6** set public + description/homepage/topics/license → **S7** report the push result/repository visibility/open-source configuration status.
7. If the address is still not in place at the S4 commit, the commit will inevitably contain placeholders; **S2 must be completed before pushing, followed by one additional commit**; pushing placeholders or fabricated URLs into a public repository is strictly forbidden.

---

## 5. Consistency notes versus the implementation

- The licensing statements of the 9 open-source files and `.github/workflows/ci.yml` are uniformly **Apache-2.0**; `LICENSE` is the complete original text (11358 bytes, terms rewritten zero times).
- Version `1.0.0` is consistent in five places: `app/__init__.py::__version__`, `pyproject.toml`, `CITATION.cff`, `CHANGELOG.md`, `SECURITY.md`; `/health.version` reads `__version__` at runtime, and **open-source badges/version/license/repo info must never be written into `/health`**.
- `pyproject.toml` has no `[build-system]`; `requirements.txt` remains the sole dependency source; `[tool.pytest.ini_options]` contains only `testpaths = ["tests"]`.
- Placeholder replacement **must not** touch the zero-change list: `web/index.html`, `requirements.txt`, `samples/knowledge.txt`, `docs/reference/*` (including `platform-spec-README.md:648`), the four `Makefile` target commands, `config/settings.yaml`.

> **Document status**: S2 has been executed (see §6); the placeholders in the deliverable files have all been replaced with real values; the §1 symbol definitions in this table are retained as a historical index.


---

## 6. S2 execution record (executed by the lead)

The user provided the account homepage `https://github.com/Nephets1010` and authorized the lead (主理人) to define the repository name; the target branch was required to match the local one.
Verification confirmed no same-name repository under that account (GitHub API 404), so a new public repository was created.

| Symbol | Actual value | Basis |
| --- | --- | --- |
| `__REPO_URL__` | `https://github.com/Nephets1010/multimodal-agent-platform` | User account + repository name defined by the lead (consistent with the local directory and pyproject's name) |
| `__OWNER__` | `Nephets1010` | Parsed from the user-provided account |
| `__REPO_NAME__` | `multimodal-agent-platform` | Parsed from the final URL segment |
| `__CI_BADGE_URL__` | `https://github.com/Nephets1010/multimodal-agent-platform/actions/workflows/ci.yml/badge.svg` | Derived one-way from `__REPO_URL__` |
| `__DEFAULT_BRANCH__` | `main` | The user required consistency with the local branch, which is main |
| `__AUTHOR_NAME__` | `Nephets1010` | User-confirmed git global identity |
| `__AUTHOR_EMAIL__` | `stephen_rong@foxmail.com` | User-confirmed git global identity email (the user is aware it is publicly visible) |
| `__COPYRIGHT_YEAR__` | `2026` | Current year |
| `__COPYRIGHT_HOLDER__` | `Nephets1010` | Consistent with the author name |
| `__SECURITY_CONTACT__` | `stephen_rong@foxmail.com` | A real, privately receivable reporting channel; a GitHub Security Advisories entry also exists |
| `__RELEASE_DATE__` | `2026-11-07` | Taken from the date command, not fabricated |

**Replacement scope**: 8 actual artifacts (README.md / pyproject.toml / CITATION.cff / CONTRIBUTING.md /
CODE_OF_CONDUCT.md / SECURITY.md / CHANGELOG.md / NOTICE); LICENSE and ci.yml never contained symbols in the first place.
The symbols in this registry and the three OPENSOURCE design documents under docs are definitions and explanatory text, excluded from the S2 check scope.

**Synchronized corrections**: sentences contradicting the final state ("replace before release / placeholder version / must not push before replacement is done") were rewritten to reflect the real state
(README §8.1/§8.4/§8.7, pyproject comments, SECURITY §2, CODE_OF_CONDUCT §3,
CONTRIBUTING community links, CHANGELOG Unreleased), and CI/License/Python badges were added to the README's first screen.

**Verification**: the S2 residue-check command (§4 item 3) actually ran with 0 residues; the 12 URLs are fully identical; no old-branch spellings;
TOML/CFF are parseable; the five-step verification is all green.
