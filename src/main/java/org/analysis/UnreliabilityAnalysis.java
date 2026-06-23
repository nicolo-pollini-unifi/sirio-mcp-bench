package org.analysis;

import org.faultTree.StaticFaultTree;

import java.math.BigDecimal;

public abstract class UnreliabilityAnalysis {
    protected StaticFaultTree faultTree;

    public UnreliabilityAnalysis(StaticFaultTree faultTree) {
        this.faultTree = faultTree;
    }

    /**
     * Computes the transient state of the unreliability over time.
     *
     * @return A 2D array where each row contains [time, probability].
     */
    public abstract BigDecimal[][] computeTransientState();

    /**
     * Computes the steady state probability of the system failure.
     *
     * @return The steady state probability.
     */
    public abstract double computeSteadyState();

}
