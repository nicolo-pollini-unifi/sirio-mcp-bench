package org.faultTree;

import com.google.common.graph.MutableValueGraph;
import org.analysis.AnalysisParameters;
import org.analysis.DeltaAnalysisParameters;
import org.oristool.models.gspn.GSPNTransient;
import org.oristool.models.gspn.chains.DTMC;
import org.oristool.models.gspn.reachability.GSPNReachability;
import org.oristool.models.gspn.reachability.SPNState;
import org.oristool.models.stpn.MarkingExpr;
import org.oristool.petrinet.Marking;
import org.oristool.petrinet.PetriNet;
import org.oristool.util.Pair;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

public class ComponentNode {
    private GSPN componentGSPN;
    private String failureCondition;
    private List<Marking> failureMarking;
    private double[] failureSolution;
    private boolean analyzed;
    private String identifier;
    private boolean stateAnalyzed;
    private Pair<Map<Marking, Integer>,double[][]> stateAnalysisResult;
    Map<Marking, Double> steadyAnalysisResult;
    private boolean steadyStateAnalyzed;

    public ComponentNode(ComponentNode node) {
        this.componentGSPN = node.componentGSPN;
        this.failureCondition = node.failureCondition;
        this.failureMarking = node.failureMarking;
        this.failureSolution = node.failureSolution;
        this.analyzed = node.analyzed;
        this.identifier = node.identifier;
        this.stateAnalyzed = node.stateAnalyzed;
        this.stateAnalysisResult = node.stateAnalysisResult;
        this.steadyAnalysisResult = node.steadyAnalysisResult;
        this.steadyStateAnalyzed = node.steadyStateAnalyzed;
    }

    public double[] getFailureSolution() {
        return failureSolution;
    }

    public String getName() {
        return identifier;
    }

    public void setName(String identifier) {
        this.identifier = identifier;
    }

    public ComponentNode(GSPN componentGSPN, String identifier, String failureCondition) {
        this.identifier=identifier;
        this.componentGSPN = componentGSPN;
        this.failureCondition = failureCondition;
        this.analyzed = false;
        this.stateAnalyzed = false;
        this.steadyStateAnalyzed = false;
        this.stateAnalysisResult = null;
        this.steadyAnalysisResult = null;
        this.failureSolution = null;
    }

    public GSPN getComponentGSPN() {
        return componentGSPN;
    }

    public String getFailureCondition() {
        return failureCondition;
    }

    public List<Marking> getFailureMarking() {
        return failureMarking;
    }

    public boolean isAnalyzed() {
        return analyzed;
    }

    public void getTransitionRatesToFailure(AnalysisParameters parameters, BigDecimal t_analysis){
        PetriNet pn = componentGSPN.getPetriNet();
        Marking marking = componentGSPN.getMarking();
        DeltaAnalysisParameters deltaParameters = (DeltaAnalysisParameters) parameters;
        double step = deltaParameters.getDelta().doubleValue();
        double startTime  = 0.0;
        BigDecimal endTime = parameters.getMaxTime();

        Pair<Map<Marking, Integer>, double[][]> result = GSPNTransient.builder()
                .timePoints(startTime, endTime.doubleValue(), step)
                .build().compute(pn, marking);

        DTMC<SPNState> gspngraph = GSPNReachability.builder().build().compute(pn, marking);
        MutableValueGraph<SPNState, Double> probgraph = gspngraph.probsGraph();
    }

    public BigDecimal analyzeComponentFailureProbability(BigDecimal maxTime, BigDecimal timeStep, BigDecimal t_analysis) {
        int index = t_analysis.divide(timeStep,50, RoundingMode.HALF_DOWN).intValue();

        if(analyzed){
            return BigDecimal.valueOf(failureSolution[index]);
        }

        PetriNet pn = componentGSPN.getPetriNet();
        Marking marking = componentGSPN.getMarking();
        double step = timeStep.doubleValue();
        double startTime  = 0.0;
        BigDecimal endTime = maxTime;
        MarkingExpr markingExpr = MarkingExpr.from(failureCondition, componentGSPN.getPetriNet());

        Pair<Map<Marking, Integer>, double[][]> result = GSPNTransient.builder()
                .timePoints(startTime, endTime.doubleValue(), step)
                .build()
                .compute(pn, marking);

        Map<Marking, Integer> statePos = result.first();
        double[][] probs = result.second();
        failureMarking = new ArrayList<>();
        for (Marking m : statePos.keySet()) {
            if (markingExpr.evaluate(m)> 0) {
                failureMarking.add(m);
            }
        }

        if (failureMarking.isEmpty()) {
            int steps = probs.length;
            failureSolution = new double[steps];
            for (int t = 0; t < probs.length; t++) {
                failureSolution[t] = 0.0;
            }
            analyzed = true;
            return BigDecimal.valueOf(failureSolution[index]);
        }

        int steps = probs.length;
        failureSolution = new double[steps];
        for(Marking failureMarkingEntry : failureMarking){
            int markingPos = statePos.get(failureMarkingEntry);
            for (int t = 0; t < probs.length; t++) {
                failureSolution[t] = probs[t][markingPos];
            }
        }
        analyzed = true;
        return BigDecimal.valueOf(failureSolution[index]);
    }

    public void setAnalyzed(boolean analyzed) {
        this.analyzed = analyzed;
        if(!analyzed){
            failureSolution = null;
        }
    }
    public void setStateAnalyzed(boolean stateAnalyzed){
        this.stateAnalyzed = stateAnalyzed;
        if(!stateAnalyzed){
            stateAnalysisResult = null;
        }
    }
    public void setSteadyStateAnalyzed (boolean steadyStateAnalyzed){
        this.steadyStateAnalyzed = steadyStateAnalyzed;
        if(!steadyStateAnalyzed){
            this.steadyAnalysisResult = null;
        }
    }

}
