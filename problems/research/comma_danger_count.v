From Stdlib Require Import Arith Bool List.
Import ListNotations.

(* y is the most significant base-b digit of c. *)

Definition leading_digit (b y c : nat) : Prop :=
  1 <= y < b /\ exists k : nat, y * b ^ k <= c < (y + 1) * b ^ k.

(* With x = a mod b the last digit of a, the successor has the form a+bx+y. *)
Definition comma_candidate (b a y : nat) : nat := a + b * (a mod b) + y.

(* c follows a: c uses the least y that is the leading digit of a+bx+y. *)
Definition comma_step (b a c : nat) : Prop :=
  exists y : nat,
    leading_digit b y (comma_candidate b a y) /\ c = comma_candidate b a y /\
    (forall y', y' < y -> ~ leading_digit b y' (comma_candidate b a y')).

(* No y works, so a comma sequence reaching a terminates at a. *)
Definition landmine (b a : nat) : Prop :=
  forall y : nat, ~ leading_digit b y (comma_candidate b a y).

(* Consecutive entries of the list are consecutive comma-sequence terms. *)
Fixpoint comma_path (b : nat) (l : list nat) : Prop :=
  match l with
  | a :: ((c :: _) as rest) => comma_step b a c /\ comma_path b rest
  | _ => True
  end.

(* v is in the danger interval [b^m - b^2, b^m), and its comma sequence
   terminates with every term below b^m. v may itself be the landmine. *)
Definition trapped (b m v : nat) : Prop :=
  b ^ m <= v + b ^ 2 /\ v < b ^ m /\
  exists rest : list nat,
    comma_path b (v :: rest) /\ Forall (fun a => a < b ^ m) (v :: rest) /\
    landmine b (last (v :: rest) v).

Definition has_cardinality {A : Type} (P : A -> Prop) (k : nat) : Prop :=
  exists xs : list A, NoDup xs /\ (forall x, In x xs <-> P x) /\ length xs = k.

Definition triangular (n : nat) : nat := n * (n + 1) / 2.

(* r(k) = #{(u, w) : u > w >= 1, T(u) = T(w) + k}. Every such pair has
   u <= k, because T(u) - T(w) >= T(u) - T(u-1) = u. *)
Definition triangular_differences (k : nat) : nat :=
  length (filter (fun '(u, w) => (w <? u) && (triangular u =? triangular w + k))
                 (list_prod (seq 1 k) (seq 1 k))).

(* The count plus one is r(1) + ... + r(b); this avoids subtracting one. *)

Theorem comma_danger_count : forall b m : nat,
  2 <= b -> 3 <= m ->
  exists c : nat,
    has_cardinality (trapped b m) c /\
    c + 1 = list_sum (map triangular_differences (seq 1 b)).
Proof.
Admitted.
