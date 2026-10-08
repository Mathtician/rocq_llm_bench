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

(* The pair is (s(p), s(p+1)), following the binary digits of p. *)
Fixpoint stern_pair (p : positive) : nat * nat :=
  match p with
  | xH => (1, 1)
  | xO q => let '(a, b) := stern_pair q in (a, a + b)
  | xI q => let '(a, b) := stern_pair q in (a + b, b)
  end.
Definition stern (n : nat) : nat :=
  match N.of_nat n with
  | N0 => 0
  | Npos p => fst (stern_pair p)
  end.

Theorem short_bsd_stern : forall n : nat,
  has_cardinality (short_bsd n) (stern n).
Proof.
Admitted.
