package org.analysis;

import org.faultTree.StaticFaultTree;

public abstract class UnreliabilityAnalysisBuilder {

    protected StaticFaultTree staticFaultTree;

    public UnreliabilityAnalysisBuilder(StaticFaultTree faultTree) {
        this.staticFaultTree = faultTree;
    }
}
