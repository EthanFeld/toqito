"""Computes the upper bound for a given Bipartite bell inequality."""

from itertools import combinations

import cvxpy as cp
import mosek
import numpy as np
from scipy.sparse import eye

from toqito.channels import partial_transpose
from toqito.perms import permutation_operator, swap


def MN_matrix(m: int, a: int, x: int) -> np.ndarray:
    r"""Compute the matrices M_a^x and N_b^y.

    Args:
        m: The number of measurement settings for Alice and Bob.
        a: The specific measurement setting for Alice.
        x: The specific measurement setting for Bob.

    Returns:
        The computed matrix.

    """
    # Create a permutation list as done in MATLAB
    perm = list(range(m + 1))  # MATLAB indices start from 1
    perm[0] = x
    perm[x] = 0

    # Calculate the matrix as in the MATLAB code
    MN = a * np.eye(2 ** (m + 1)) + ((-1) ** a) * permutation_operator([2] * (m + 1), perm, 0, 1)

    return MN


def bell_inequality_max(joint_coe, a_coe, b_coe, a_val, b_val):
    r"""Return the upper bound for the maximum violation(Tsirelson Bound) for a given bipartite Bell Inequality.

    This computes the upper bound for the maximum value of a given bipartite Bell Inequality using SDP.
    The method is from :cite:`Navascues_2014_Characterization` and the implementation is based on :cite:`QETLAB_link`.
    This is useful for various tasks in device independent quantum information processing

    The function formulates the problem as a SDP problem in the following format

    .. math::
        \[
        \max \operatorname{tr} \left( W \cdot \sum_{a,b,x,y} B^{xy}_{ab} M^x_a \otimes N^y_b \right),
        \]
        \[
        \text{s.t.} \quad \operatorname{tr}(W) = 1, \quad W \geq 0,
        \]
        \[
        W^{T_P} \geq 0, \quad \text{for all bipartitions } P.
        \]
        \]

    Examples
    =======


    Consider the I3322 Bell inequality
    . . math::
    I_{3322} = P(A_1 = B_1) + P(B_1 = A_2) + P(A_2 = B_2) + P(B_2 = A_3)
           - P(A_1 = B_2) - P(A_2 = B_3) - P(A_3 = B_1) - P(A_3 = B_3)
           \leq 2

    The individual and joint coefficents and measurement values are encoded as matrices.
    The upper bound can then be found in :code:'toqito' as follows.

    >>> from toqito.state_opt import bell_inequality_max
    >>> import numpy as np
    >>> joint_coe = np.array([
    ... [1, 1, -1],
    ... [1, 1, 1],
    ... [-1, 1, 0]
    ... ])
    >>> a_coe = np.array([0, -1, 0])
    >>> b_coe = np.array([-1, -2, 0])
    >>> a_val = np.array([0,1])
    >>> b_val = np.array([0,1])
    >>> '%.3f' % bell_inequality_max(joint_coe, a_coe, b_coe, a_val, b_val)
    '0.250'

    References
    ==========
    .. bibliography::
        :filter: docname in docnames

    :raises ValueError: If a_val or b_val are not length 2.
    :param joint_coe: The coefficents for terms containing both A and B
    :param a_coe: The coefficent for terms only containing A
    :param b_coe: The coefficent for terms only containing B
    :param a_val: The value of each measurement outcome for A
    :param b_val: The value of each measurement outcome for B
    :return: The upper bound for the maximum violation of the Bell inequality



    """
    m, _ = joint_coe.shape
    oa = len(a_val)
    ob = len(b_val)

    # Ensure the input vectors are column vectors
    a_val = a_val.reshape(-1, 1)
    b_val = b_val.reshape(-1, 1)
    a_coe = a_coe.reshape(-1, 1)
    b_coe = b_coe.reshape(-1, 1)

    # Check if vectors a_val and b_val have only two elements
    if oa != 2 or ob != 2:
        raise ValueError("This script is only capable of handling Bell inequalities with two outcomes.")

    tot_dim = 2 ** (2 * m + 2)
    obj_mat = np.zeros((tot_dim, tot_dim), dtype=float)

    # Nested loops to compute the objective matrix
    for a in range(2):  # a = 0 to 1
        for b in range(2):  # b = 0 to 1
            for x in range(1, m + 1):  # x = 1 to m (1-indexed in MATLAB, hence the range adjustment)
                for y in range(1, m + 1):  # y = 1 to m
                    b_coeff = (
                        joint_coe[x - 1, y - 1] * a_val[a, 0] * b_val[b, 0]
                    )  # Adjust index for 0-based Python indexing
                    if y == 1:
                        b_coeff += a_coe[x - 1, 0] * a_val[a, 0]  # Adjust for 0-based indexing
                    if x == 1:
                        b_coeff += b_coe[y - 1, 0] * b_val[b, 0]  # Adjust for 0-based indexing

                    # Adding the result of the tensor product to the objective matrix
                    obj_mat += b_coeff * np.kron(MN_matrix(m, a, x), MN_matrix(m, b, y))

    # Symmetrize the matrix to avoid numerical issues
    obj_mat = (obj_mat + obj_mat.T) / 2
    aux_mat = np.array([[1, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]])

    # Construct the SDP problem
    W = cp.Variable((2 ** (2 * m), 2 ** (2 * m)), symmetric=True)

    M = swap(W, [2, m + 1], [2] * (2 * m))
    X = swap(cp.kron(M, aux_mat), [m + 1, 2 * m + 1], [2] * (2 * m + 2))
    Z = swap(X, [m + 2, 2 * m + 1], [2] * (2 * m + 2))

    objective = cp.Maximize(cp.trace(Z @ obj_mat))

    # Define the constraints
    constraints = [cp.trace(W) == 1, W >> 0]

    # Adding PPT constraints
    for sz in range(1, m + 1):
        # Generate all combinations of indices from 1 to 2*m-1 of size sz
        for ppt_partition in combinations(range(1, 2 * m - 1), sz):
            # Convert to 0-based indexing for Python
            ppt_partition_updated = [x - 1 for x in ppt_partition]
            # Partial transpose on the partition, ensuring it's positive semidefinite
            pt_matrix = partial_transpose(W, ppt_partition_updated, [4] + [2] * (2 * (m - 1)))
            constraints.append(pt_matrix >> 0)

    # Solve the problem
    prob = cp.Problem(objective, constraints)
    prob.solve(solver="MOSEK", verbose=False)

    # Return the results
    rho = W.value
    bmax = prob.value

    return bmax
