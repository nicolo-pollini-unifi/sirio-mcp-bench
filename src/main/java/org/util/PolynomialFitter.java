package org.util;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.List;

public class PolynomialFitter {
    public static BigDecimal fitToZero(List<BigDecimal> hs, List<BigDecimal> ys, int scale) {
        int n = hs.size();
        double[][] A = new double[3][3];
        double[] B = new double[3];

        for (int i = 0; i < n; i++) {
            double h = hs.get(i).doubleValue();
            double y = ys.get(i).doubleValue();
            A[0][0] += 1;
            A[0][1] += h;
            A[0][2] += h * h;
            A[1][0] += h;
            A[1][1] += h * h;
            A[1][2] += h * h * h;
            A[2][0] += h * h;
            A[2][1] += h * h * h;
            A[2][2] += h * h * h * h;

            B[0] += y;
            B[1] += y * h;
            B[2] += y * h * h;
        }

        double[] coeffs = solveLinearSystem(A, B);
        return new BigDecimal(coeffs[0]).setScale(scale, RoundingMode.HALF_UP); // a0 is value at h=0
    }

    private static double[] solveLinearSystem(double[][] A, double[] B) {
        int n = 3;
        for (int i = 0; i < n; i++) {
            int max = i;
            for (int j = i + 1; j < n; j++)
                if (Math.abs(A[j][i]) > Math.abs(A[max][i])) max = j;

            double[] tempA = A[i];
            A[i] = A[max];
            A[max] = tempA;

            double tempB = B[i];
            B[i] = B[max];
            B[max] = tempB;

            for (int j = i + 1; j < n; j++) {
                double alpha = A[j][i] / A[i][i];
                B[j] -= alpha * B[i];
                for (int k = i; k < n; k++) {
                    A[j][k] -= alpha * A[i][k];
                }
            }
        }
        double[] x = new double[n];
        for (int i = n - 1; i >= 0; i--) {
            x[i] = B[i];
            for (int j = i + 1; j < n; j++)
                x[i] -= A[i][j] * x[j];
            x[i] /= A[i][i];
        }
        return x;
    }
}

