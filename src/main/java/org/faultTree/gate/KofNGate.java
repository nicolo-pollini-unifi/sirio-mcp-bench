package org.faultTree.gate;

import org.faultTree.ComponentNode;
import org.faultTree.StaticFaultTree;

import java.util.*;

public class KofNGate extends Gate {
    private int k;
    private StaticFaultTree ANDORRepresentation;

    public KofNGate(String identifier,int k) {
        super(identifier);
        this.k = k;
    }

    public KofNGate(String identifier, List<Gate> gates,List<ComponentNode> nodes,int k) {
        super(identifier,gates,nodes);
        this.k = k;
        this.ANDORRepresentation = transformKONToOrOfAndFT();
    }

    public StaticFaultTree getANDORRepresentation() {
        if (this.ANDORRepresentation != null){
            return ANDORRepresentation;
        }else{
            this.ANDORRepresentation = transformKONToOrOfAndFT();
            return ANDORRepresentation;
        }
    }

    public int getK(){
        return k;
    }

//    @Override
//    public Set<Set<ComponentNode>> getMinCutSets() {
//        return ANDORRepresentation.getMinCutSets();
//    }

    @Override
    public synchronized Set<Set<ComponentNode>> getMinCutSets() {
        if (minCutSetsCache != null) return minCutSetsCache;

        // collect children MCS sources
        List<Set<Set<ComponentNode>>> sources = new ArrayList<>();

        for (ComponentNode n : nodes) {
            sources.add(Set.of(Set.of(n)));
        }

        for (Gate g : gates) {
            sources.add(g.getMinCutSets());
        }

        Set<Set<ComponentNode>> result = new HashSet<>();

        combineK(0, 0, new ArrayList<>(), sources, result);

        minCutSetsCache = filterMinCutSets(result);
        return minCutSetsCache;
    }

    private void combineK(
            int start,
            int chosen,
            List<Set<Set<ComponentNode>>> picked,
            List<Set<Set<ComponentNode>>> sources,
            Set<Set<ComponentNode>> result) {

        if (chosen == k) {
            // AND them
            Set<Set<ComponentNode>> acc = Set.of(Set.of());

            for (Set<Set<ComponentNode>> src : picked) {
                Set<Set<ComponentNode>> next = new HashSet<>();
                for (Set<ComponentNode> a : acc) {
                    for (Set<ComponentNode> b : src) {
                        Set<ComponentNode> u = new HashSet<>(a);
                        u.addAll(b);
                        if (u.size() <= MAX_ORDER) {
                            next.add(u);
                        }
                    }
                }
                acc = next;
            }

            result.addAll(acc);
            return;
        }

        for (int i = start; i <= sources.size() - (k - chosen); i++) {
            picked.add(sources.get(i));
            combineK(i + 1, chosen + 1, picked, sources, result);
            picked.remove(picked.size() - 1);
        }
    }

    private Set<Set<ComponentNode>> filterMinCutSets(Set<Set<ComponentNode>> cutSets) {
        List<Set<ComponentNode>> sorted = new ArrayList<>(cutSets);
        sorted.sort(Comparator.comparingInt(Set::size));

        Set<Set<ComponentNode>> minCutSets = new HashSet<>();
        for (Set<ComponentNode> candidate : sorted) {
            boolean isMinimal = minCutSets.stream().noneMatch(candidate::containsAll);
            if (isMinimal) {
                minCutSets.add(candidate);
            }
        }
        return minCutSets;
    }

    private StaticFaultTree transformKONToOrOfAndFT(){
        List<Set<ComponentNode>> individualMCS = new ArrayList<>();
        for (ComponentNode node : nodes) {
            individualMCS.add(Collections.singleton(node));
        }
        for(Gate gate : gates) {
            individualMCS.addAll(gate.getMinCutSets());
        }
        int index =0;
        Set<Set<ComponentNode>> kCombinations = getCombinations(individualMCS, k);
        List<Gate> andGates = new ArrayList<>();
        List<ComponentNode> newNodes = new ArrayList<>();
        for (Set<ComponentNode> combination : kCombinations) {
            if(combination.size() == 1){
                newNodes.add((ComponentNode) combination.toArray()[0]);
            }else {
                List<ComponentNode> nodesAsFaultTrees = new ArrayList<>();
                for (ComponentNode node : combination) {
                    nodesAsFaultTrees.add(new ComponentNode(node));
                }
                ANDGate newAndGate = new ANDGate(identifier + "_" + "KoN_AND_" + index++);
                newAndGate.setNodes(nodesAsFaultTrees);
                andGates.add(newAndGate);
            }
        }
        ORGate orGate = new ORGate(identifier+ "_" + "KoN_OR_"+ index++);
        orGate.setGates(andGates);
        orGate.setNodes(newNodes);
        return new StaticFaultTree(orGate);
    }

    private Set<Set<ComponentNode>> getCombinations(List<Set<ComponentNode>> sets, int k) {
        Set<Set<ComponentNode>> result = new HashSet<>();
        getCombinationsHelper(sets, k, 0, new HashSet<>(), result);
        return result;
    }

    private void getCombinationsHelper(List<Set<ComponentNode>> sets, int k, int start, Set<ComponentNode> current, Set<Set<ComponentNode>> result) {
        if (k == 0) {
            result.add(new HashSet<>(current));
            return;
        }
        for (int i = start; i < sets.size(); i++) {
            current.addAll(sets.get(i));
            getCombinationsHelper(sets, k - 1, i + 1, current, result);
            current.removeAll(sets.get(i));
        }
    }

    @Override
    public void addNode(ComponentNode node){
        if(!nodes.contains(node)){
            this.nodes.add(node);
        }
        this.ANDORRepresentation = transformKONToOrOfAndFT();
    }

    @Override
    public void addGate(Gate gate){
        if(!gates.contains(gate)){
            this.gates.add(gate);
        }
        this.ANDORRepresentation = transformKONToOrOfAndFT();
    }

    @Override
    public Gate copy() {
        Gate copyGate = new KofNGate(this.identifier, this.k);
        for(Gate gate: gates){
            Gate newGate = gate.copy();
            copyGate.addGate(newGate);
        }
        for(ComponentNode node: nodes){
            ComponentNode newNode = new ComponentNode(node);
            copyGate.addNode(newNode);
        }
        return copyGate;
    }

    public void setK(int k) {
        this.k=k;
    }

    @Override
    public double estimateLogMCS() {

        // Collect child log-values
        List<Double> childLogs = new ArrayList<>();

        for (Gate g : gates) {
            childLogs.add(g.estimateLogMCS());
        }

        // ComponentNodes contribute 1 MCS each → log10(1) = 0
        for (int i = 0; i < nodes.size(); i++) {
            childLogs.add(0.0);
        }

        int n = childLogs.size();

        if (k > n || k <= 0) {
            return Double.NEGATIVE_INFINITY;
        }

        // DP[j] = log10 of sum of products choosing j children
        double[] dp = new double[k + 1];
        Arrays.fill(dp, Double.NEGATIVE_INFINITY);
        dp[0] = 0.0;  // log10(1)

        for (double logVal : childLogs) {
            for (int j = k; j >= 1; j--) {
                if (dp[j - 1] != Double.NEGATIVE_INFINITY) {

                    double candidate = dp[j - 1] + logVal;

                    dp[j] = logSum10(dp[j], candidate);
                }
            }
        }

        return dp[k];
    }

    private double logSum10(double a, double b) {

        if (a == Double.NEGATIVE_INFINITY) return b;
        if (b == Double.NEGATIVE_INFINITY) return a;

        double max = Math.max(a, b);
        double min = Math.min(a, b);

        return max + Math.log10(1 + Math.pow(10, min - max));
    }

    @Override
    public Set<Set<ComponentNode>> getMinCutSetsTotal() {
        List<Set<Set<ComponentNode>>> sources = new ArrayList<>();

        for (ComponentNode n : nodes) {
            sources.add(Set.of(Set.of(n)));
        }

        for (Gate g : gates) {
            sources.add(g.getMinCutSetsTotal());
        }

        Set<Set<ComponentNode>> result = new HashSet<>();

        combineKTotal(0, 0, new ArrayList<>(), sources, result);

        minCutSetsCache = filterMinCutSets(result);
        return minCutSetsCache;
    }

    private void combineKTotal(
            int start,
            int chosen,
            List<Set<Set<ComponentNode>>> picked,
            List<Set<Set<ComponentNode>>> sources,
            Set<Set<ComponentNode>> result) {

        if (chosen == k) {
            // AND them
            Set<Set<ComponentNode>> acc = Set.of(Set.of());

            for (Set<Set<ComponentNode>> src : picked) {
                Set<Set<ComponentNode>> next = new HashSet<>();
                for (Set<ComponentNode> a : acc) {
                    for (Set<ComponentNode> b : src) {
                        Set<ComponentNode> u = new HashSet<>(a);
                        u.addAll(b);
                        next.add(u);
                    }
                }
                acc = next;
            }

            result.addAll(acc);
            return;
        }

        for (int i = start; i <= sources.size() - (k - chosen); i++) {
            picked.add(sources.get(i));
            combineKTotal(i + 1, chosen + 1, picked, sources, result);
            picked.remove(picked.size() - 1);
        }
    }

}
