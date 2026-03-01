### Getting started

The file `main.py` provides an example of how to set everything up. 

If you run it as is, it'll open a browser to preview the chart as shown below.

You can use `Market.logs.to_csv(file)` to save the entire dispatch schedule (including offline units). 

<b>Note</b>: The load data for the current preview is truncated. It comes from the daily DK1 load data by ENTSO-E Transparency (ranging between 2015 - 2020). You can use the full range (just modify Setup class) but bear in mind it's computationally intensive. 

<img width="1917" height="855" alt="image" src="https://github.com/user-attachments/assets/a95498fc-0f4a-426e-96df-b0484d34252d" />
