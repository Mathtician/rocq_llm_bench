From Stdlib Require Import ZArith List.
Import ListNotations.

(* F_0 = 0, F_1 = F_2 = 1. Positions 1 and 2 are distinct digit positions. *)

Fixpoint fib (i : nat) : Z :=
  match i with
  | 0 => 0%Z
  | S p => match p with
           | 0 => 1%Z
           | S q => (fib p + fib q)%Z
           end
  end.

(* Digits are most significant first: [a_k; ...; a_1] has value
   a_k*F_k + ... + a_1*F_1. Leading zeroes are allowed; the length is fixed. *)
Fixpoint fib_value (ds : list Z) : Z :=
  match ds with
  | [] => 0%Z
  | d :: rest => (d * fib (S (length rest)) + fib_value rest)%Z
  end.

Definition signed_zero_rep (k : nat) (ds : list Z) : Prop :=
  length ds = k /\ Forall (fun d => (-1 <= d <= 1)%Z) ds /\ fib_value ds = 0%Z.

Definition has_cardinality {A : Type} (P : A -> Prop) (k : nat) : Prop :=
  exists xs : list A, NoDup xs /\ (forall x, In x xs <-> P x) /\ length xs = k.

(* 1, 1, 3, 5, 9, 17, ...; the value at 0 counts the empty list. *)
Fixpoint trib (k : nat) : nat :=
  match k with
  | 0 => 1
  | S p => match p with
           | 0 => 1
           | S q => match q with
                    | 0 => 3
                    | S r => trib p + trib q + trib r
                    end
           end
  end.

Theorem fib_signed_zero_trib : forall k : nat,
  has_cardinality (signed_zero_rep k) (trib k).
Proof.
Admitted.
