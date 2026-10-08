# Research pilot

Seventeen fixed Rocq statements for the next benchmark phase. Build with
`uv run rlb tier research`; this checks every statement through the actual
solution verifier and checks all available references before replacing the
`research` tier. The thirteen paper tasks have **no Rocq reference proof yet**:
successful statement compilation is not a proof of truth or faithful translation.
Each of the ten added on 2026-09-23 is instead proved in Rocq for its smallest
instances (see Validation), which checks that the definitions count exactly
what the paper counts there.
All tasks use Stdlib and compile under Rocq 9.1.1.

| Task | Mathematical target | Ground truth / role |
|---|---|---|
| `short_bsd_stern` | Number of short signed-binary representations of n equals Stern(n) | Published informal proof, Theorem 2; candidate main task |
| `short_bsd_hyperbinary` | Short representations of n+1 and hyperbinary representations of n have the same finite cardinality | Published informal proof, Theorem 3; candidate main task |
| `parking_count` | Generalized parking-function count for all a,b,n | Published informal proof; candidate main task |
| `lucky_one_unlucky` | Preference lists in [n]^n with exactly one unlucky car are counted by the total quicksort comparisons over all n! orderings | Published informal proof, Theorem 1 |
| `parking_exced_des` | For each parking content, strict excedances of b∘w and descents of its parking outcome are equidistributed over w | Published informal proof, Theorem 3.1 (proof machine-generated, lightly refereed) |
| `cyclic_4321_213_fib` | Cyclic permutations avoiding 4321 (one-line) and 213 (standard cycle form) number F(2n−3) | Published informal proof, Corollary 3.6 |
| `cyclic_rot1432_4321` | Cyclic permutations avoiding 4321 with every cycle rotation avoiding 1432 number 2^(n−1) − ⌊(3n−5)/2⌋ | Published informal proof, Theorem 1.2 (paper: n≥5; stated from n=3) |
| `vpf_nonincreasing` | Non-increasing vacillating parking functions satisfy v(n) = 2v(n−1) + v(n−3) | Published informal proof, Theorem 3.6 |
| `fib_signed_zero_trib` | Length-k signed Fibonacci-digit representations of 0 are counted by a Tribonacci recurrence | Published informal proof, Theorem 1.1 |
| `quaternary_shift` | Hyperquaternary counts at [2…2]₄ + n equal balanced-quaternary counts at n on the stated interval | Published informal proof, Theorem 1.2 |
| `digit_insert_rank` | The rank of 10n among one-digit insertions into n is the digit sum of n | Published informal proof, Theorem 6 |
| `hofstadter3_death` | The three-term Hofstadter-like recurrence from 1..N has exactly N+24 terms for N ≥ 14 | Published informal proof, Theorem 1 |
| `comma_danger_count` | Base-b comma sequences trapped in [b^m−b², b^m) are counted by triangular differences | Published informal proof, Theorem 2 (paper: m≥2, false; stated for m≥3) |
| `medial_walk_01`, `medial_walk_02` | Locally generated identities implied by the medial law | Verified references (not shipped in the public release; regenerate with `uv run python scripts/generate-research-equations.py`); uncalibrated algebra controls |
| `medial_countermodel_01`, `medial_countermodel_02` | Three-element countermodels to nearby mutated identities | Verified witnesses; counterexample controls |

No model trials have been run to calibrate these tasks. In particular, a
32-step generated proof is not evidence that the shortest proof is difficult.
The algebra controls should not be described as harder than Putnam problems.
The initial timeout is a provisional four hours per task, overridable with
`--timeout`; it is not an estimated completion time.

## Sources and translation choices

**Binary representations:** Katie Anders, Madeline Locus Dawsey, Rajat Gupta,
and Joseph Vandehey, [Non-Standard Binary Representations and the Stern
Sequence](https://www.combinatorics.org/ojs/index.php/eljc/article/view/v31i4p39),
Electronic Journal of Combinatorics 31(4), P4.39 (2024),
[DOI 10.37236/12312](https://doi.org/10.37236/12312).

Digits are lists of integers in most-significant-first order. Values are
weighted sums, not a counting recurrence. Digits must be in {-1,0,1}; a short
representation is nonempty, has no leading zero, and its first two digits
(when present) are not opposite nonzero digits. This includes both possible
leading signs, so positivity of the value is a mathematical consequence rather
than an extra restriction. Zero has no short representation. Hyperbinary digits
are in {0,1,2}, with no leading zero; the empty list represents zero exactly once.
Theorem 3 uses n+1 and n to avoid natural-number subtraction at zero; its omitted
zero endpoint in the paper is the separate convention f_HB(-1)=0.

Stern's sequence is computed by binary recursion on the pair (s(p),s(p+1)).
The input supplies this sequence definition, but no recurrence for the counts,
enumeration bound, bijection, or supporting theorem.

**Parking functions:** AJ Bu and Doron Zeilberger,
[A Short Proof that the number of (a,b)-parking functions of length n is
a(a+bn)^(n-1)](https://arxiv.org/abs/2412.11222v2), v2 (2024).

Preferences are ordered lists of positive naturals. The predicate requires a
sorted permutation whose zero-based entry i is at most a+b*i. The count is over
the original lists, not over their sorted permutations. At n=0 the count is 1;
at positive n it is a*(a+b*n)^(n-1), including a=0 and b=0. This avoids interpreting
the paper's negative exponent at n=0 as truncated natural subtraction. Version 2
also discusses earlier proofs, so the cited note is a proof source, not a claim
that this formula was first discovered in 2024.

All three tasks use `has_cardinality P k`: there is a duplicate-free list of
length k containing exactly the objects satisfying P. Exact coverage is an
iff, so neither extraneous objects nor omitted representations are allowed.
This uses ordinary lists and Prop predicates without a new finite-set library.
For the two binary tasks, retain the identical shared definitions when editing.

**Signed Fibonacci representations:** Katie Anders, Madeline L. Dawsey, and Joseph Vandehey, [Non-standard Zeckendorf decompositions; or, Tribonacci within Fibonacci](https://arxiv.org/abs/2604.15446v1), v1 (2026). Digits are lists of integers in {-1,0,1}, most significant first. The last digit is weighted by F_1, and F_1 = F_2 = 1 are distinct positions. Length is fixed and leading zeroes are allowed. The Tribonacci side starts 1, 1, 3. The paper gives B(0;1..3) = 1, 3, 5 and the recurrence from k = 3. The k = 0 case (the empty list, counted once) is our extension, consistent with the recurrence.

**Quaternary representations:** Katie Anders, Madeline L. Dawsey, Rajat Gupta, Noah Lebowitz-Lockard, and Joseph Vandehey, [Non-standard quaternary representations and the Fibonacci numbers](https://arxiv.org/abs/2505.04589v1), v1 (2025). Both digit sets use the binary tasks' conventions: no leading zero, and the empty list represents zero. Hyperquaternary digits are 0..4 and balanced digits are -2..2. `repdigit c j` is the numeral with j copies of c, as in the paper's notation. The statement uses j ≥ 1, as in the paper's Theorem 3.1, and gives only the equality; the paper's sharpness claim is checked in the tests, not stated. These two tasks and the two binary tasks share authors and methods, so all four form one family (`nonstandard_representations`).

**Lucky cars:** Pamela E. Harris, Jan Kretschmann, and J. Carlos Martínez Mori, [Lucky Cars and the Quicksort Algorithm](https://arxiv.org/abs/2306.13065v1), v1 (2023), Amer. Math. Monthly (2024). Preference lists are arbitrary words in [n]^n, not only parking functions. A car takes the first free spot at or after its preference, or leaves; it is lucky only if it parks at its preference. Exactly n−1 lucky cars is written `lucky + 1 = n`, so the empty list is not counted. The formula side is the paper's headline quantity: the sum of quicksort comparisons over a duplicate-free list of all orderings of 1..n, with the first entry as pivot and stable partition. This total equals the paper's A_n for any fixed pivot position. The paper states n ≥ 2; the statement holds, and is stated, for every n.

**Parking statistics:** Colin Defant, [Short Proofs in Algebraic and Enumerative Combinatorics](https://arxiv.org/abs/2605.19979v3), v3, Theorem 3.1, which implies Hopkins's conjecture (Corollary 3.2). The paper says its proofs were produced by an AI system. A parking content is a weakly increasing list with 1 ≤ b_j ≤ j. For a permutation w of 1..n, π_i = b_{w(i)}. Excedances are strict and one-based. The outcome σ lists, car by car, the spot each car parks in. It is not the inverse listing of cars by spot, which makes the identity false from n = 4. The polynomial identity is stated coefficientwise: for every k, the two sets of permutations w have the same finite cardinality.

**Cyclic permutations:** Junyao Pan, [On two conjectures about pattern avoidance of cyclic permutations](https://arxiv.org/abs/2505.02045v1), v1, Corollary 3.6; Zuo-Ru Zhang and Hongkuan Zhao, [On a question about pattern avoidance of cyclic permutations](https://arxiv.org/abs/2603.06269v1), v1, Theorem 1.2. Permutations are one-line lists of 1..n. The standard cycle form is (1, π(1), π²(1), …), and a permutation is cyclic when this list has no repeats. Pattern containment asks for an order-isomorphic subsequence, which need not be consecutive. Rotations include the standard form itself. Sizes are n+2 and n+3 to avoid subtraction; the second formula is stated as m + ⌊(3n+4)/2⌋ = 2^(n+2). Zhang–Zhao state n ≥ 5. The statement also covers sizes 3 and 4, where the formula has been checked; it fails at sizes 1 and 2. Both counts are unchanged under the opposite cycle-direction convention. For the two tasks, retain the identical shared definitions when editing.

**Vacillating parking:** Bruce Fang, Pamela E. Harris, Brian M. Kamau, and David Wang, [Vacillating parking functions](https://arxiv.org/abs/2402.02538v2), v2, Theorem 3.6. A car preferring p tries p, then p−1, then p+1, and takes the first of these that exists and is free; otherwise the list fails. Lists are non-increasing, with entries in 1..n. The count follows the paper's recurrence with initial values 1, 3, 6 at n = 1, 2, 3, plus one empty list at n = 0, so the recurrence begins at n = 4. The paper's Theorem 3.6 says n ≥ 1 but refers to v(n−3). Its generating function implicitly uses v(0) = 0, which contradicts its own |VPF_0| = 1.

**Digit insertion:** Sela Fried, [Proofs of Ten Conjectures From the OEIS](https://cs.uwaterloo.ca/journals/JIS/VOL29/Fried/fried21.pdf), Journal of Integer Sequences 29 (2026), Article 26.1.8, Theorem 6. S(n) is a set of values: one decimal digit is inserted at any of the length+1 gaps, and results with a leading zero are excluded. Different insertions giving the same number count once. The rank of 10n is stated as 10n ∈ S(n) plus the count of elements at most 10n. The statement quantifies over n together with its decimal expansion, which forces n ≥ 1.

**Three-term Hofstadter-like recurrence:** Nathan Fox, [The Behavior of a Three-Term Hofstadter-Like Recurrence with Linear Initial Conditions](https://arxiv.org/abs/2406.00904v1), v1 (2024), Journal of Integer Sequences 27, Article 24.7.4, Theorem 1. Terms are an option-valued extension of the list B(1..len). A new term is undefined when any index it needs lies outside 1..n−1, which is the paper's "dies" (the paper's wording names only the first lag). "Exactly N+24 terms" means 24 further terms exist and the 25th does not.

**Comma sequences:** Robert Dougherty-Bliss and Natalya Ter-Saakov, [The Comma Sequence is Finite in Other Bases](https://arxiv.org/abs/2408.03434v2), v2 (2024), Journal of Integer Sequences 28, Article 25.5.5, Theorem 2. The successor follows Definition 1: the least y whose value equals the leading digit of a + b·(a mod b) + y. The leading digit is stated with powers, not a digit function. A start value is counted when some chain of successors stays below b^m and ends at a value with no successor; the start value may itself be that value. The paper's generating function is replaced by the partial sums it encodes: the count plus one equals r(1)+…+r(b), where r(k) counts pairs u > w ≥ 1 with T(u) − T(w) = k. Theorem 2 says m ≥ 2, but the paper's own Definition 6 says k > 2, and m = 2 is false (base 3: both 3 and 4 are trapped below 9, while the formula gives 1; the tests prove this in Rocq). The statement uses m ≥ 3.

**Equational theories:** inspired by the
[Equational Theories Project](https://teorth.github.io/equational_theories/).
The specific expressions come from `scripts/generate-research-equations.py`,
with seeds and generation details in `equations.json`. A nonrepeating random
walk applies the medial identity inside binary terms. Swapping two leaves gives
a negative control with the same variable multiplicities. Each mutation is
screened against an affine operation on three elements. These are fresh
expressions built from a standard mathematical law, not novel mathematical
results. The generator checks no notion of minimum proof length.

The positive tasks quantify over arbitrary types and operations. The negative
tasks demand a length-nine table on `option bool`, the medial law, and a specific
violating assignment. They cannot be discharged merely by excluded middle on
an unrestricted "prove or disprove" disjunction.

## Validation and provenance

`metadata.json` records source versions, the light pre-screen on 2026-09-09,
task families, reference status, and timeout. Searches for the paper titles and
parking/Stern/hyperbinary terms with Rocq, Coq, or Lean did not surface an exact
Rocq formalization. A local installed-source search also found none. This is a
limited negative search result, not an absence guarantee. Public informal
solutions are expected and permitted in the intended open-search evaluation.
Inspect agent logs for reuse of formal proofs in any language.

Validation command:

```sh
uv run pytest -q tests/test_research.py tests/test_research_combinatorics.py tests/test_research_numbertheory.py tests/test_verify.py
```

Checks include statement re-elaboration, rejection of admitted references,
kernel verification of all four algebra references, deterministic regeneration,
actual Rocq predicate examples, and independent small-case enumeration for the
paper formulas. Finite tests are sanity checks, not general reference proofs. For the ten tasks
added on 2026-09-23 the tests also turn the theorem text itself into a Prop and
prove it in Rocq for the smallest instances (e.g. `lucky_one_unlucky` for
n = 0..5, `parking_exced_des` for every content of length 4), and they pin each
boundary convention the source papers get wrong with a Rocq `Example`.

## Evaluation use

The generated `problems/research/*.v` files are the benchmark inputs. The source
README, metadata, generator, and `.ref.v` files are curator material. Keep
references inaccessible to trial processes, as in the existing harness.
Related tasks share methods: split/report by `family`, not by individual file,
and do not treat the two binary tasks or an algebra positive/negative pair as
independent evidence of generalization.

The existing runner recognizes `--tier research`, but its network sandbox and
single-agent setup are still the phase-one policies. Adding this tier does not
enable internet search or delegation. Use it with a future open-search harness
profile for the intended phase-two comparison; ordinary `rlb run` remains a
restricted baseline. No subscription usage, agent trials, or ledger commits
are triggered by importing this tier.
