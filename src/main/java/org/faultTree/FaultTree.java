package org.faultTree;

import org.faultTree.gate.Gate;

import java.util.Set;

public abstract class FaultTree {
    protected Gate rootGate;

    public FaultTree(final Gate rootGate) {
        this.rootGate = rootGate;
    }

    public Gate getRootGate() {
        return rootGate;
    }

    public void setRootgate(Gate rootGate) {
        this.rootGate = rootGate;
    }

    public int getnComponents() {
        return rootGate.getnComponents();
    }

    public Set<ComponentNode> getAllNodes(){
        return rootGate.getAllNodes();
    }

    @Override
    public String toString() {
        StringBuilder sb = new StringBuilder();
        sb.append("Fault Tree Structure: { ").append("\n");
        sb.append(rootGate.toString());
        sb.append(" }");
        return sb.toString();
    }

    public void resetAnalysis() {
        rootGate.resetAnaylysis();
    }

}
