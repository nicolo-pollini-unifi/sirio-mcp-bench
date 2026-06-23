package org.analysis;

import org.faultTree.ComponentNode;
import org.faultTree.StaticFaultTree;
import org.faultTree.gate.ANDGate;
import org.faultTree.gate.Gate;
import org.faultTree.gate.KofNGate;
import org.faultTree.gate.ORGate;
import org.oristool.models.gspn.GSPNSteadyState;
import org.oristool.models.gspn.GSPNTransient;
import org.oristool.models.pn.PostUpdater;
import org.oristool.models.pn.Priority;
import org.oristool.models.stpn.MarkingExpr;
import org.oristool.models.stpn.trees.StochasticTransitionFeature;
import org.oristool.petrinet.*;
import org.oristool.util.Pair;
import org.util.BooleanComplement;

import java.math.BigDecimal;
import java.math.MathContext;
import java.util.*;

public class SystemAnalysis extends UnreliabilityAnalysis{
    private BigDecimal maxTime;
    private BigDecimal error;
    private BigDecimal delta;
    private MathContext MC;
    private boolean debug;
    private PetriNet systemPetriNet;
    private Marking systemMarking;
    private Map<String, String> components;
    private String failureCondition;

    public SystemAnalysis(StaticFaultTree staticFaultTree){
        super(staticFaultTree);
        this.systemPetriNet = new PetriNet();
        this.systemMarking = new Marking();
        this.components = new HashMap<>();
        this.failureCondition = processFaultTree(faultTree);
    }

    public PetriNet getSystemPetriNet() {
        return systemPetriNet;
    }

    public Marking getSystemMarking(){
        return systemMarking;
    }
    /**
     * Computes the transient state analysis for the system unreliability.
     * Evaluates the system failure probability over the specified time range and steps.
     *
     * @return A Matrix of BigDecimal containing [timestamp, unreliability_value].
     */
    @Override
    public BigDecimal[][] computeTransientState() {
        double step = delta.doubleValue();
        double startTime = 0.0;
        double endTime = maxTime.doubleValue();
        MarkingExpr markingExpr = MarkingExpr.from(failureCondition, systemPetriNet);

        // Perform GSPN transient analysis
        Pair<Map<Marking, Integer>, double[][]> result = GSPNTransient.builder()
                .timePoints(startTime, endTime, step)
                .build().compute(systemPetriNet, systemMarking);

        Map<Marking, Integer> statePos = result.first();
        double[][] probs = result.second();
        int nSteps = probs.length;

        // Initialize probability array
        BigDecimal[] failureSolution = new BigDecimal[nSteps];
        for (int i = 0; i < nSteps; i++) {
            failureSolution[i] = BigDecimal.ZERO;
        }

        // Sum probabilities of all markings that satisfy the failure condition
        boolean foundFailureMarking = false;
        for (Map.Entry<Marking, Integer> entry : statePos.entrySet()) {
            if (markingExpr.evaluate(entry.getKey()) > 0) {
                int markingPos = entry.getValue();
                for (int t = 0; t < nSteps; t++) {
                    failureSolution[t] = failureSolution[t].add(BigDecimal.valueOf(probs[t][markingPos]));
                }
                foundFailureMarking = true;
            }
        }

        if (!foundFailureMarking) {
            throw new IllegalStateException("No reachable marking satisfies the failure condition.");
        }

        // Prepare results array [time, probability]
        BigDecimal[][] failureArray = new BigDecimal[nSteps][2];
        for (int i = 0; i < nSteps; i++) {
            failureArray[i][0] = delta.multiply(BigDecimal.valueOf(i), MC);
            failureArray[i][1] = failureSolution[i];
        }

        this.faultTree.resetAnalysis();
        return failureArray;
    }

    /**
     * Computes the steady state probability of the system failure.
     * Iterates over all reachable markings and sums the probabilities of those
     * that satisfy the failure condition.
     *
     * @return The steady state probability of system failure.
     */
    @Override
    public double computeSteadyState(){
        MarkingExpr markingExpr = MarkingExpr.from(failureCondition, systemPetriNet);

        Map<Marking, Double> result = GSPNSteadyState.builder().build().compute(systemPetriNet, systemMarking);

        double steadyStateProb = 0.0;
        boolean found = false;

        for (Map.Entry<Marking, Double> entry : result.entrySet()) {
            if (markingExpr.evaluate(entry.getKey()) > 0) {
                steadyStateProb += entry.getValue();
                found = true;
            }
        }

        if (!found) {
            throw new IllegalStateException("No marking satisfies the condition.");
        }

        this.faultTree.resetAnalysis();
        return steadyStateProb;
    }

    private String processFaultTree(StaticFaultTree faultTree) {
        Gate rootGate = faultTree.getRootGate();
        return processGate(rootGate, true) + ">0";
    }
    private String processGate(Gate gate, boolean root){
        if(gate instanceof ANDGate){
            return processANDGate((ANDGate)gate, root);
        }else if(gate instanceof ORGate){
            return processORGate((ORGate)gate, root);
        }else if (gate instanceof KofNGate){
            return processKofNGate((KofNGate)gate, root);
        }
        throw new IllegalStateException("Unsupported GATE type");
    }

    private String processANDGate(ANDGate gate, boolean root) {
        List<String> gateFailurePlaces = new ArrayList<>();
        for(Gate entrygate : gate.getGates()){
            String failurePlace = processGate(entrygate, false);
            gateFailurePlaces.add(failurePlace);
        }

        Set<String> nodeFailurePlaces = new HashSet<>();
        for(ComponentNode node : gate.getNodes()){
            String nodeFailurePlace = createComponentPetriNetCopy(systemPetriNet, systemMarking, node);
            nodeFailurePlaces.add(nodeFailurePlace);
        }

        Place failurePlace = systemPetriNet.addPlace(gate.getIdentifier() + "_ANDfailure");
        Transition failureTransition = systemPetriNet.addTransition(gate.getIdentifier()+ "_failTrans");
        failureTransition.addFeature(StochasticTransitionFeature.newDeterministicInstance(BigDecimal.ZERO));
        failureTransition.addFeature(new Priority(41));
        StringBuilder transitionConditionBuilder = new StringBuilder();
        for(String gateFailurePlace : gateFailurePlaces){
            transitionConditionBuilder.append("*");
            if(transitionConditionBuilder.toString().equals("*")){
                transitionConditionBuilder = new StringBuilder(gateFailurePlace + "*");
            }
            transitionConditionBuilder.append(gateFailurePlace);
        }
        for(String nodeFailurePlace : nodeFailurePlaces){
            transitionConditionBuilder.append("*");
            if(transitionConditionBuilder.toString().equals("*")){
                transitionConditionBuilder = new StringBuilder(nodeFailurePlace+ "*");
            }
            transitionConditionBuilder.append(nodeFailurePlace);
        }
        String gateFailTransitionCondition = transitionConditionBuilder.toString();
        gateFailTransitionCondition = gateFailTransitionCondition + " > 0 && " + failurePlace + " == 0";
        failureTransition.addFeature(new EnablingFunction(gateFailTransitionCondition));
        if(root) {
            StringBuilder markingUpdateStringBuilder = new StringBuilder();
            Collection<Place> places = systemPetriNet.getPlaces();
            for(Place place : places){
                if(!place.equals(failurePlace)){
                    markingUpdateStringBuilder.append(place.getName()).append(" = 0 ;");
                }
            }
            String markingUpdateString = markingUpdateStringBuilder.toString();
            failureTransition.addFeature(new PostUpdater(markingUpdateString, systemPetriNet));
        }
        systemPetriNet.addPostcondition(failureTransition,failurePlace);

        transitionConditionBuilder.append(" < 1");
        String resetCondition = transitionConditionBuilder.toString();
        if(!root){
            Transition resetTransition = systemPetriNet.addTransition(gate.getIdentifier()+ "_resetTrans");
            resetTransition.addFeature(StochasticTransitionFeature.newDeterministicInstance(BigDecimal.ZERO));
            resetTransition.addFeature(new Priority(42));
            resetTransition.addFeature(new EnablingFunction(resetCondition));
            systemPetriNet.addPrecondition(failurePlace,resetTransition);
        }
        return failurePlace.getName();
    }

    private String processORGate(ORGate gate, boolean root) {
        List<String> gateFailurePlaces = new ArrayList<>();
        for(Gate entrygate : gate.getGates()){
            String failurePlace = processGate(entrygate, false);
            gateFailurePlaces.add(failurePlace);
        }

        Set<String> nodeFailurePlaces = new HashSet<>();
        for(ComponentNode node : gate.getNodes()){
            String nodeFailurePlace = createComponentPetriNetCopy(systemPetriNet, systemMarking, node);
            nodeFailurePlaces.add(nodeFailurePlace);
        }

        Place failurePlace = systemPetriNet.addPlace(gate.getIdentifier() + "_ORfailure");
        Transition failureTransition = systemPetriNet.addTransition(gate.getIdentifier() + "_failTrans");
        failureTransition.addFeature(StochasticTransitionFeature.newDeterministicInstance(BigDecimal.ZERO));
        failureTransition.addFeature(new Priority(41));
        StringBuilder resetConditionBuilder = new StringBuilder();
        for(String gateFailurePlace : gateFailurePlaces){
            resetConditionBuilder.append("+");
//            if(resetConditionBuilder.toString().equals("+")){
//                resetConditionBuilder = new StringBuilder(gateFailurePlace + "+");
//            }
            resetConditionBuilder.append(gateFailurePlace);
        }
        for(String nodeFailurePlace : nodeFailurePlaces){
            resetConditionBuilder.append("+");
//            if(resetConditionBuilder.toString().equals("+")){
//                resetConditionBuilder = new StringBuilder(nodeFailurePlace + "+");
//            }
            resetConditionBuilder.append(nodeFailurePlace);
        }
        String gateFailTransitionCondition = resetConditionBuilder.toString();
        gateFailTransitionCondition = gateFailTransitionCondition + " > 0 && " + failurePlace + " == 0";
        failureTransition.addFeature(new EnablingFunction(gateFailTransitionCondition));
        if(root) {
            StringBuilder markingUpdateStringBuilder = new StringBuilder();
            Collection<Place> places = systemPetriNet.getPlaces();
            for(Place place : places){
                if(!place.equals(failurePlace)){
                    markingUpdateStringBuilder.append(place.getName()).append(" = 0 ;");
                }
            }
            String markingUpdateString = markingUpdateStringBuilder.toString();
            failureTransition.addFeature(new PostUpdater(markingUpdateString, systemPetriNet));
        }
        systemPetriNet.addPostcondition(failureTransition,failurePlace);

        resetConditionBuilder.append(" < 1 ");
        String resetCondition = resetConditionBuilder.toString();
        if(!root){
            Transition resetTransition = systemPetriNet.addTransition(gate.getIdentifier() + " _resetTrans ");
            resetTransition.addFeature(StochasticTransitionFeature.newDeterministicInstance(BigDecimal.ZERO));
            resetTransition.addFeature(new Priority(42));
            resetTransition.addFeature(new EnablingFunction(resetCondition));
            systemPetriNet.addPrecondition(failurePlace,resetTransition);
        }
        return failurePlace.getName();
    }

    private String processKofNGate(KofNGate gate, boolean root) {
        List<String> gateFailurePlaces = new ArrayList<>();
        for(Gate entrygate : gate.getGates()){
            String failurePlace = processGate(entrygate, false);
            gateFailurePlaces.add(failurePlace);
        }

        Set<String> nodeFailurePlaces = new HashSet<>();
        for(ComponentNode node : gate.getNodes()){
            String nodeFailurePlace = createComponentPetriNetCopy(systemPetriNet, systemMarking, node);
            nodeFailurePlaces.add(nodeFailurePlace);
        }

        Place failurePlace = systemPetriNet.addPlace(gate.getIdentifier() + "_ORfailure");
        Transition failureTransition = systemPetriNet.addTransition(gate.getIdentifier() + "_failTrans");
        failureTransition.addFeature(StochasticTransitionFeature.newDeterministicInstance(BigDecimal.ZERO));
        failureTransition.addFeature(new Priority(41));
        StringBuilder resetConditionBuilder = new StringBuilder();
        for(String gateFailurePlace : gateFailurePlaces){
            resetConditionBuilder.append("+");
//            if(resetConditionBuilder.toString().equals("+")){
//                resetConditionBuilder = new StringBuilder(gateFailurePlace + "+");
//            }
            resetConditionBuilder.append(gateFailurePlace);
        }
        for(String nodeFailurePlace : nodeFailurePlaces){
            resetConditionBuilder.append("+");
//            if(resetConditionBuilder.toString().equals("+")){
//                resetConditionBuilder = new StringBuilder(nodeFailurePlace + "+");
//            }
            resetConditionBuilder.append(nodeFailurePlace);
        }
        String gateFailTransitionCondition = resetConditionBuilder.toString();
        gateFailTransitionCondition = gateFailTransitionCondition + " >=  " + gate.getK() + " && " + failurePlace + " == 0";
        failureTransition.addFeature(new EnablingFunction(gateFailTransitionCondition));
        if(root) {
            StringBuilder markingUpdateStringBuilder = new StringBuilder();
            Collection<Place> places = systemPetriNet.getPlaces();
            for(Place place : places){
                if(!place.equals(failurePlace)){
                    markingUpdateStringBuilder.append(place.getName()).append(" = 0 ;");
                }
            }
            String markingUpdateString = markingUpdateStringBuilder.toString();
            failureTransition.addFeature(new PostUpdater(markingUpdateString, systemPetriNet));
        }
        systemPetriNet.addPostcondition(failureTransition,failurePlace);
        resetConditionBuilder.append(" < " + gate.getK());
        String resetCondition = resetConditionBuilder.toString();
        if(!root){
            Transition resetTransition = systemPetriNet.addTransition(gate.getIdentifier() + " _resetTrans ");
            resetTransition.addFeature(StochasticTransitionFeature.newDeterministicInstance(BigDecimal.ZERO));
            resetTransition.addFeature(new Priority(42));
            resetTransition.addFeature(new EnablingFunction(resetCondition));
            systemPetriNet.addPrecondition(failurePlace,resetTransition);
        }
        return failurePlace.getName();
    }

    private String createComponentPetriNetCopy( PetriNet systemPetriNet, Marking systemMarking, ComponentNode componentNode) {

        String failurePlaceName;

        if(components.containsKey(componentNode.getName())){
            failurePlaceName = components.get(componentNode.getName());
        }else{
            PetriNet gspnPetriNet = componentNode.getComponentGSPN().getPetriNet();
            Marking gspnMarking = componentNode.getComponentGSPN().getMarking();
            String nodeName = componentNode.getName();

            for(Place place : gspnPetriNet.getPlaces()) {
                systemPetriNet.addPlace(nodeName +"_"+place.getName());
            }
            for(Transition transition : gspnPetriNet.getTransitions()) {
                Transition systemTransition = systemPetriNet.addTransition(nodeName +"_"+transition.getName());

                Collection<TransitionFeature> transitionFeatures =transition.getFeatures();
                for(TransitionFeature transitionFeature : transitionFeatures){
                    systemTransition.addFeature(transitionFeature);
                }

                Collection<InhibitorArc> inhibArcs = gspnPetriNet.getInhibitorArcs(transition);
                for(InhibitorArc arc : inhibArcs) {
                    Place gspnInhibPlace = arc.getPlace();
                    Place systemInhibPlace = systemPetriNet.getPlace(nodeName +"_"+gspnInhibPlace.getName());
                    systemPetriNet.addInhibitorArc(systemInhibPlace,systemTransition);
                }

                Collection<Precondition> preconditions = gspnPetriNet.getPreconditions(transition);
                for(Precondition precondition : preconditions) {
                    Place prePlace = systemPetriNet.getPlace(nodeName+"_"+precondition.getPlace().getName());
                    systemPetriNet.addPrecondition(prePlace, systemTransition);
                }
                Collection<Postcondition> postconditions = gspnPetriNet.getPostconditions(transition);
                for(Postcondition postcondition : postconditions) {
                    Place postPlace = systemPetriNet.getPlace(nodeName+"_"+postcondition.getPlace().getName());
                    systemPetriNet.addPostcondition(systemTransition,postPlace);
                }
            }

            for(String placeName : gspnMarking.getNonEmptyPlacesNames()){
                Place place = systemPetriNet.getPlace(nodeName+"_"+placeName);
                systemMarking.addTokens(place, gspnMarking.getTokens(placeName));
            }

            Place failurePlace = systemPetriNet.addPlace(nodeName +"_failurePlace");
            Transition failureTransition = systemPetriNet.addTransition(nodeName +"_failureTransition");
            String enablingFunctionLimiter = " && " + failurePlace.getName() + " == 0";
            failureTransition.addFeature(new EnablingFunction(nodeName+"_"+componentNode.getFailureCondition()+enablingFunctionLimiter));
            failureTransition.addFeature(StochasticTransitionFeature.newDeterministicInstance(BigDecimal.ZERO));
            failureTransition.addFeature(new Priority(41));
            systemPetriNet.addPostcondition(failureTransition, failurePlace);
            Transition resetTransition = systemPetriNet.addTransition(nodeName +"_resetTransition");
            String complementfailureCondition = nodeName+"_"+ BooleanComplement.complementExpression(componentNode.getFailureCondition());
            resetTransition.addFeature(new EnablingFunction(complementfailureCondition));
            resetTransition.addFeature(StochasticTransitionFeature.newDeterministicInstance(BigDecimal.ZERO));
            resetTransition.addFeature(new Priority(42));
            systemPetriNet.addPrecondition(failurePlace,resetTransition);
            failurePlaceName = failurePlace.getName();
            components.put(componentNode.getName(),failurePlaceName);
        }

        return failurePlaceName;
    }

    public BigDecimal getMaxTime() {
        return maxTime;
    }

    public void setMaxTime(BigDecimal maxTime) {
        this.maxTime = maxTime;
    }

    public BigDecimal getError() {
        return error;
    }

    public void setError(BigDecimal error) {
        this.error = error;
    }

    public BigDecimal getDelta() {
        return delta;
    }

    public void setDelta(BigDecimal delta) {
        this.delta = delta;
    }

    public MathContext getMC() {
        return MC;
    }

    public void setMC(MathContext MC) {
        this.MC = MC;
    }

    public void debug(boolean debug){
        this.debug = debug;
    }



}
