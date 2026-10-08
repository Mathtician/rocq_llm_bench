(** Putnam 2025 Problem B5

    Let p be a prime > 3.  For each k ∈ {1, ..., p-1}, let I(k)
    be the modular inverse of k mod p (the unique element in
    {1, ..., p-1} with k * I(k) ≡ 1 (mod p)).

    Prove that
      #{k ∈ {1, ..., p-2} | I(k+1) < I(k)} > p/4 - 1.

    We work entirely in Z and multiply through to avoid fractions:

4 * count + 4 > p, i.e., 4 * count ≥ p - 3. *)

From Stdlib Require Import ZArith Znumtheory List.
Import ListNotations.
Open Scope Z_scope.

(** I(k) is the modular inverse of k mod p, in {1, ..., p-1}. *)
Definition is_mod_inverse (p k inv_k : Z) : Prop :=
  1 <= inv_k <= p - 1 /\ (k * inv_k) mod p = 1 mod p.

(** Existence and uniqueness of modular inverses for 1 ≤ k ≤ p-1
    when p is prime.  We take I as a parameter. *)

Definition valid_inverse_fun (p : Z) (I : Z -> Z) : Prop :=
  forall k, 1 <= k <= p - 1 -> is_mod_inverse p k (I k).

(** The count of descents:
    #{k ∈ {1, ..., p-2} | I(k+1) < I(k)}. *)
Definition descent_count (p : Z) (I : Z -> Z) : Z :=
  let indices := List.map Z.of_nat (seq 1 (Z.to_nat (p - 2))) in
  Z.of_nat (length (filter (fun k => I (k + 1) <? I k) indices)).

(** Statement: the descent count is strictly greater than p/4 - 1,
    i.e., 4 * count + 4 > p, equivalently 4 * count >= p - 3. *)

Theorem putnam_2025_b5 :
  forall (p : Z) (I : Z -> Z),
    prime p ->
    p > 3 ->
    valid_inverse_fun p I ->
    4 * descent_count p I >= p - 3.
Proof.
Admitted.
