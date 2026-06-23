package org.analysis;

import org.faultTree.StaticFaultTree;

import java.math.BigDecimal;
import java.math.MathContext;

public class SystemAnalysisBuilder extends UnreliabilityAnalysisBuilder{
    private BigDecimal error;
    private BigDecimal maxTime;
    private BigDecimal timeStep;
    private boolean debug;
    private MathContext MC;

    public SystemAnalysisBuilder(StaticFaultTree faultTree) {
        super(faultTree);
        error = BigDecimal.valueOf(0.001);
        MC = new MathContext(50);
    }

    public SystemAnalysisBuilder setError(final BigDecimal error) {
        this.error = error;
        return this;
    }

    public SystemAnalysisBuilder setMaxTime(final BigDecimal maxTime) {
        this.maxTime = maxTime;
        return this;
    }

    public SystemAnalysisBuilder setTimeStep(final BigDecimal timeStep) {
        this.timeStep = timeStep;
        return this;
    }

    public SystemAnalysisBuilder setDebug(final boolean debug) {
        this.debug = debug;
        return this;
    }

    public SystemAnalysisBuilder setMC(final MathContext mc) {
        this.MC = mc;
        return this;
    }

    public SystemAnalysis build() {
        if(staticFaultTree == null || maxTime == null || timeStep == null) {
            throw new IllegalArgumentException("All required parameters must not be null");
        }
        SystemAnalysis sa = new SystemAnalysis(staticFaultTree);
        sa.setMaxTime(maxTime);
        sa.setDelta(timeStep);
        sa.setError(error);
        sa.debug(debug);
        sa.setMC(MC);
        return sa;
    }

    public void clear(){
        staticFaultTree = null;
        error = null;
        maxTime = null;
        timeStep = null;
        debug = false;
        MC = null;
    };
}
