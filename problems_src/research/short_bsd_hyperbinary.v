From Stdlib Require Import ZArith List.
Import ListNotations.

(* Digits are most significant first. Leading zeroes are not representations. *)
Fixpoint binary_value (ds : list Z) : Z :=
  match ds with
  | [] => 0%Z
  | d :: rest => (d * 2 ^ Z.of_nat (length rest) + binary_value rest)%Z
  end.

Definition short_bsd (n : nat) (ds : list Z) : Prop :=
  Forall (fun d => (-1 <= d <= 1)%Z) ds /\
  (match ds with
   | [] => False
   | d :: [] => d <> 0%Z
   | d :: e :: _ => d <> 0%Z /\ (d + e <> 0)%Z
   end) /\ binary_value ds = Z.of_nat n.

Definition has_cardinality {A : Type} (P : A -> Prop) (k : nat) : Prop :=
  exists xs : list A, NoDup xs /\ (forall x, In x xs <-> P x) /\ length xs = k.

(* The empty list is the unique representation of zero. *)
Definition hyperbinary (n : nat) (ds : list Z) : Prop :=
  Forall (fun d => (0 <= d <= 2)%Z) ds /\
  (match ds with [] => True | d :: _ => d <> 0%Z end) /\
  binary_value ds = Z.of_nat n.

Theorem short_bsd_hyperbinary : forall n : nat, exists k : nat,
  has_cardinality (short_bsd (S n)) k /\
  has_cardinality (hyperbinary n) k.
Proof.
Admitted.
