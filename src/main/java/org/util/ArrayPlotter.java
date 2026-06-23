package org.util;

import org.jfree.chart.ChartFactory;
import org.jfree.chart.ChartPanel;
import org.jfree.chart.JFreeChart;
import org.jfree.chart.axis.LogAxis;
import org.jfree.chart.plot.PlotOrientation;
import org.jfree.chart.plot.XYPlot;
import org.jfree.data.xy.XYSeries;
import org.jfree.data.xy.XYSeriesCollection;

import javax.swing.*;
import java.math.BigDecimal;

public class ArrayPlotter {

    public static double[][] convertBigDecimalArray(BigDecimal[][] input) {
        int rows = input.length;
        int cols = input[0].length;
        double[][] output = new double[rows][cols];

        for (int i = 0; i < rows; i++) {
            for (int j = 0; j < cols; j++) {
                output[i][j] = input[i][j].doubleValue();
            }
        }
        return output;
    }
    private XYSeriesCollection dataset;
    private JFreeChart chart;
    private JFrame frame;
    private int seriesCounter = 1;

    public ArrayPlotter(String title) {
        dataset = new XYSeriesCollection();
        chart = ChartFactory.createXYLineChart(
                title,
                "X",
                "Y",
                dataset,
                PlotOrientation.VERTICAL,
                true,
                true,
                false
        );

        frame = new JFrame(title);
        frame.setDefaultCloseOperation(JFrame.EXIT_ON_CLOSE);
        frame.add(new ChartPanel(chart));
        frame.pack();
        frame.setVisible(true);
    }

    public ArrayPlotter(String title, boolean logScale) {
        dataset = new XYSeriesCollection();
        chart = ChartFactory.createXYLineChart(
                title,
                "X",
                "Y",
                dataset,
                PlotOrientation.VERTICAL,
                true,
                true,
                false
        );

        if(logScale){
            XYPlot plot = chart.getXYPlot();
            LogAxis xAxis = new LogAxis("X (log)");
            LogAxis yAxis = new LogAxis("Y (log)");
            xAxis.setBase(10);
            yAxis.setBase(10);

            // Optional: prevent exceptions from log(0)
            xAxis.setSmallestValue(0.0001);
            yAxis.setSmallestValue(0.0001);

            plot.setDomainAxis(xAxis); // X-axis
            plot.setRangeAxis(yAxis);  // Y-axis

            frame = new JFrame(title);
            frame.setDefaultCloseOperation(JFrame.EXIT_ON_CLOSE);
            frame.add(new ChartPanel(chart));
            frame.pack();
            frame.setVisible(true);
        }else{
            frame = new JFrame(title);
            frame.setDefaultCloseOperation(JFrame.EXIT_ON_CLOSE);
            frame.add(new ChartPanel(chart));
            frame.pack();
            frame.setVisible(true);
        }
    }

    public void addSeriesBD(BigDecimal[] yValues) {
        XYSeries series = new XYSeries("Series " + seriesCounter++);
        for (int i = 0; i < yValues.length; i++) {
            series.add(i, yValues[i].doubleValue());
        }
        dataset.addSeries(series);
    }

    public void addSeriesBD(BigDecimal[] xValues, BigDecimal[] yValues) {
        if (xValues.length != yValues.length) {
            throw new IllegalArgumentException("X and Y arrays must be the same length.");
        }
        XYSeries series = new XYSeries("Series " + seriesCounter++);
        for (int i = 0; i < xValues.length; i++) {
            series.add(xValues[i].doubleValue(), yValues[i].doubleValue());
        }
        dataset.addSeries(series);
    }

    // Y values only, X = 0, 1, 2, ...
    public void addSeries(double[] yValues) {
        XYSeries series = new XYSeries("Series " + seriesCounter++);
        for (int i = 0; i < yValues.length; i++) {
            series.add(i, yValues[i]);
        }
        dataset.addSeries(series);
    }

    // Custom X and Y values
    public void addSeries(double[] xValues, double[] yValues) {
        if (xValues.length != yValues.length) {
            throw new IllegalArgumentException("X and Y arrays must be the same length.");
        }
        XYSeries series = new XYSeries("Series " + seriesCounter++);
        for (int i = 0; i < xValues.length; i++) {
            series.add(xValues[i], yValues[i]);
        }
        dataset.addSeries(series);
    }

    public static void plot(double[][] data) {
        XYSeriesCollection dataset = new XYSeriesCollection();

        for (int i = 0; i < data.length; i++) {
            XYSeries series = new XYSeries("Series " + (i + 1));
            for (int j = 0; j < data[i].length; j++) {
                series.add(j, data[i][j]); // X is index, Y is value
            }
            dataset.addSeries(series);
        }

        JFreeChart chart = ChartFactory.createXYLineChart(
                "BigDecimal Plot",
                "X",
                "Y",
                dataset,
                PlotOrientation.VERTICAL,
                true,
                true,
                false
        );

        JFrame frame = new JFrame("Chart Example");
        frame.setDefaultCloseOperation(JFrame.EXIT_ON_CLOSE);
        frame.add(new ChartPanel(chart));
        frame.pack();
        frame.setVisible(true);
    }


}
