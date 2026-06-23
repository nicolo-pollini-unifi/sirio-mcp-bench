package org.system;

import org.faultTree.FaultTree;

public class FaultMode {
    private FaultTree faultTree;

    public FaultMode(FaultTree faultTree) {
        this.faultTree = faultTree;
    }
    public FaultTree getFaultTree() {
        return faultTree;
    }
    public void setFaultTree(FaultTree faultTree) {
        this.faultTree = faultTree;
    }

}
