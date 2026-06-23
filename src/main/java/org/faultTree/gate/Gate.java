package org.faultTree.gate;

import org.faultTree.ComponentNode;

import java.math.BigDecimal;
import java.util.*;

public abstract class Gate {
    protected List<Gate> gates;
    protected List<ComponentNode> nodes;
    protected Set<Set<ComponentNode>> minCutSetsCache;
    protected String identifier;

    public static final int MAX_ORDER = 5;  // max number of components per cut set
    protected static final boolean PARALLEL = true; // toggle parallel recursion

    public Gate(String identifier) {
        this.gates = new ArrayList<Gate>();
        this.nodes = new ArrayList<>();
        this.minCutSetsCache = null;
        this.identifier = identifier;
    }

    public Gate(String identifier, List<Gate> gates, List<ComponentNode> nodes) {
        this.gates = gates;
        this.nodes = nodes;
        this.minCutSetsCache = null;
        this.identifier = identifier;
    }

    public String getIdentifier() {
        return identifier;
    }

    public List<Gate> getGates() {
        return gates;
    }

    public void setGates(List<Gate> gates) {
        this.gates = gates;
    }

    public List<ComponentNode> getNodes() {
        return nodes;
    }

    public void setNodes(List<ComponentNode> nodes) {
        this.nodes = nodes;
    }

    public int getnComponents() {
        int nComponents = nodes.size();
        for(Gate gate : gates){
            nComponents += gate.getnComponents();
        }
        return nComponents;
    }

    public void addNode(ComponentNode node){
        if(!nodes.contains(node)){
            this.nodes.add(node);
        }
    }

    public void addGate(Gate gate){
        if(!gates.contains(gate)){
            this.gates.add(gate);
        }
    }

    public void analyzeComponents(Map<ComponentNode, BigDecimal> ctmcResults, BigDecimal maxTime, BigDecimal timeStep) {
        for (ComponentNode node : nodes) {
            BigDecimal initialFailureProbability = node.analyzeComponentFailureProbability(maxTime, timeStep, BigDecimal.ZERO);
            ctmcResults.put(node, initialFailureProbability);
//            System.out.println("Node " + node.getName() + " initial failure probability at t=0: " + initialFailureProbability.toString());
        }

        for (Gate gate : gates) {
            gate.analyzeComponents(ctmcResults, maxTime, timeStep);
        }
    }

    public abstract  Set<Set<ComponentNode>> getMinCutSets();

    public Set<ComponentNode> getAllNodes() {
        Set<ComponentNode> allNodes = new HashSet<ComponentNode>(nodes);
        for(Gate gate : gates){
            allNodes.addAll(gate.getAllNodes());
        }
        return allNodes;
    }

    public abstract Gate copy();

    public void removeNode(String name) {
        ComponentNode foundNode = null;
        for(ComponentNode node : nodes){
            if(node.getName().equals(name)){
                foundNode = node;
            }
        }
        if(foundNode != null){
            nodes.remove(foundNode);
        }
    }

    @Override
    public String toString() {
        StringBuilder sb = new StringBuilder();
        sb.append(this.getClass().getName()).append("\n");
        for(ComponentNode node : nodes) {
            sb.append(node.getName()).append(",");
        }
        sb.append("\n");
        for(Gate gate : gates) {
            sb.append("{ ").append(gate.toString()).append(" }").append("\n");
        }
        return sb.toString();
    }

    public void replaceNode(ComponentNode node, ComponentNode replacer) {
        ComponentNode foundNode = null;
        for(ComponentNode childNode : nodes){
            if(childNode.getName().equals(node.getName())){
                foundNode = childNode;
            }
        }
        if(foundNode != null){
            nodes.remove(foundNode);
            nodes.add(replacer);
        }
    }

    public void resetAnaylysis() {
        for(Gate gate : gates){
            gate.resetAnaylysis();
        }
        for(ComponentNode node : nodes){
            node.setAnalyzed(false);
            node.setStateAnalyzed(false);
            node.setSteadyStateAnalyzed(false);
        }
    }

    public abstract double estimateLogMCS();

    protected double logChoose(int n, int k) {
        double log = 0;
        for (int i = 1; i <= k; i++) {
            log += Math.log10(n - (k - i));
            log -= Math.log10(i);
        }
        return log;
    }

    public abstract Set<Set<ComponentNode>> getMinCutSetsTotal();
}
