From Stdlib Require Import ZArith List.
Import ListNotations.

(* Digits are most significant first. Leading zeroes are not representations. *)
Fixpoint quaternary_value (ds : list Z) : Z :=
  match ds with
  | [] => 0%Z
  | d :: rest => (d * 4 ^ Z.of_nat (length rest) + quaternary_value rest)%Z
  end.

(* The empty list is the unique representation of zero in both families. *)
Definition hyperquaternary (m : Z) (ds : list Z) : Prop :=
  Forall (fun d => (0 <= d <= 4)%Z) ds /\
  (match ds with [] => True | d :: _ => d <> 0%Z end) /\
  quaternary_value ds = m.

Definition balanced_quaternary (n : Z) (ds : list Z) : Prop :=
  Forall (fun d => (-2 <= d <= 2)%Z) ds /\
  (match ds with [] => True | d :: _ => d <> 0%Z end) /\
  quaternary_value ds = n.

Definition has_cardinality {A : Type} (P : A -> Prop) (k : nat) : Prop :=
  exists xs : list A, NoDup xs /\ (forall x, In x xs <-> P x) /\ length xs = k.

(* repdigit c j is the base-4 numeral with j copies of the digit c. *)
Definition repdigit (c : Z) (j : nat) : Z := quaternary_value (repeat c j).

Theorem quaternary_shift : forall (j : nat) (n : Z),
  1 <= j ->
  (- repdigit 1 j <= n <= repdigit 1 (S j))%Z ->
  exists k : nat,
    has_cardinality (hyperquaternary (repdigit 2 j + n)) k /\
    has_cardinality (balanced_quaternary n) k.
Proof.
Admitted.
