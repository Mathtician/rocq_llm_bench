From Stdlib Require Import Bool ZArith List.
Import ListNotations.

(* terms = [B(1); ...; B(len)]. B(i) is defined only for 1 <= i <= len. *)
Definition term (terms : list Z) (i : Z) : option Z :=
  if ((1 <=? i) && (i <=? Z.of_nat (length terms)))%Z
  then Some (nth (Z.to_nat (i - 1)) terms 0%Z)
  else None.

(* B(n) = B(n - B(n-1)) + B(n - B(n-2)) + B(n - B(n-3)) for n = len + 1.
   It is undefined (None) if any index used is outside 1..n-1: this covers
   nonpositive indices and references to B(n) or later terms. *)
Definition next_term (terms : list Z) : option Z :=
  let n := (Z.of_nat (length terms) + 1)%Z in
  match term terms (n - 1), term terms (n - 2), term terms (n - 3) with
  | Some a, Some b, Some c =>
      match term terms (n - a), term terms (n - b), term terms (n - c) with
      | Some x, Some y, Some z => Some (x + y + z)%Z
      | _, _, _ => None
      end
  | _, _, _ => None
  end.

(* Append k further terms, or None if the sequence dies first. *)
Fixpoint extend (terms : list Z) (k : nat) : option (list Z) :=
  match k with
  | 0 => Some terms
  | S k' => match next_term terms with
            | Some b => extend (terms ++ [b]) k'
            | None => None
            end
  end.

(* Initial conditions B(i) = i for 1 <= i <= N. *)
Definition linear_init (N : nat) : list Z := map Z.of_nat (seq 1 N).

(* Exactly N + 24 terms: B(N+1), ..., B(N+24) exist and B(N+25) does not. *)
Theorem hofstadter3_death : forall N : nat,
  14 <= N ->
  (exists terms, extend (linear_init N) 24 = Some terms) /\
  extend (linear_init N) 25 = None.
Proof.
Admitted.
